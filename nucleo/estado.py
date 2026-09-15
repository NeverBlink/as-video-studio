"""
Estado del Estudio de Video: grafo de build con versiones y granularidad por unidad.

Modelo
------
Cada paso guarda la FIRMA de las entradas con las que se ejecuto. La firma se
calcula a partir de los parametros del paso y, recursivamente, de las firmas de
sus dependencias. Si la firma actual no coincide con la guardada, el paso esta
"obsoleto". No hay que marcar nada a mano: la obsolescencia se deriva.

Hay tres firmas por paso:

  firma_global(paso)   parametros del paso IGNORANDO el bloque "unidades",
                       encadenada con la firma_global de sus dependencias.
  firma_unidad(p, u)   firma_global(p) + los datos de esa unidad + la firma de
                       la misma unidad en las dependencias que la declaren + el
                       sello de lo que esas dependencias produjeron para ella.
  firma(paso)          todo junto: global + todas sus unidades + firmas
                       completas de las dependencias + el sello de la version
                       activa de cada dependencia.

Los "sellos" son la mitad que no se puede deducir de los parametros: la version
concreta que la dependencia tiene activa y la firma con la que produjo cada
unidad. Sin ellos, revertir una dependencia a una version vieja con los mismos
parametros no se notaria aguas abajo y el paso seguiria diciendo "listo" con
material de otra version.

Gracias a esa separacion, cambiar el texto de la escena S03 en "guion" cambia
firma(guion) y firma_unidad(*, "S03"), pero NO firma_unidad(*, "S01"): assets,
callouts y render quedan obsoletos solo en S03.

Parametros por unidad
---------------------
Los parametros de un paso pueden llevar la clave reservada "unidades":

    estado.set_params("guion", {
        "tono": "seco",
        "unidades": {"S01": {"texto": "..."}, "S02": {"texto": "..."}},
    })

Las unidades declaradas se heredan aguas abajo por el DAG, asi que "assets" no
necesita repetirlas: sus unidades son las escenas que vienen del guion.
"""
import copy
import os
import shutil

try:
    from .proyecto import (CARPETA_MANIFIESTOS, Proyecto, ahora, escribir_json,
                           huella as _huella, leer_json, lock_de, recolocar)
except ImportError:  # ejecutado con la carpeta nucleo directamente en sys.path
    from proyecto import (CARPETA_MANIFIESTOS, Proyecto, ahora, escribir_json,
                          huella as _huella, leer_json, lock_de, recolocar)

NOMBRE_ESTADO = "estado.json"
VERSION_FORMATO = 1
CLAVE_UNIDADES = "unidades"

#: Params que son CORRECCIONES DE LA SALIDA, no entradas del paso.
#:
#: Editar a mano un bloque del guion no es pedirle otro guion al modelo: es
#: arreglar el que dio. Volver a ejecutar el paso no incorporaria esa correccion
#: -- la borraria --, asi que marcarlo obsoleto propone un remedio destructivo.
#: Con veintitres bloques retocados, `guion` se quedaba obsoleto para siempre y
#: detras caian assets, callouts y render: el video salia «Obsoleto» recien
#: montado, y cada montaje volvia a recorrer pasos que no tenian nada que hacer.
#:
#: Lo que si invalidan es lo de AGUAS ABAJO, y eso no se toca: si cambias el
#: texto, la voz hay que regrabarla. Por eso solo se descuentan de la firma
#: PROPIA del paso (ver `_firma(propias=False)`), nunca de la que ven los demas.
CORRECCIONES = {"guion": ("bloques",)}

# Los `id` son el contrato (carpetas, params, firmas): NO se renombran nunca.
# El `nombre` es solo lo que se enseña, y va alineado con las pestañas de la
# interfaz: `ingesta` se enseña como «Origen» y `callouts` como «Rotulos».
PASOS = [
    {"id": "ingesta", "nombre": "Origen",
     "depende_de": [], "unidades": False},
    {"id": "brief", "nombre": "Brief",
     "depende_de": ["ingesta"], "unidades": False},
    {"id": "guion", "nombre": "Guion",
     "depende_de": ["ingesta", "brief"], "unidades": False},
    {"id": "voz", "nombre": "Voz",
     "depende_de": ["guion"], "unidades": False},
    {"id": "revision_audio", "nombre": "Revisión de audio",
     "depende_de": ["voz"], "unidades": False},
    # 'assets' se ENSEÑA como «Video», que es el nombre de su pestaña: los
    # rotulos viven dentro como una tarjeta mas, asi que la cabecera describe la
    # pestaña entera. «Assets» era un nombre tecnico, y «Planos» chocaba con la
    # tarjeta que se llama asi de verdad (la generacion de imagenes).
    {"id": "assets", "nombre": "Vídeo",
     "depende_de": ["guion", "voz"], "unidades": True},
    {"id": "callouts", "nombre": "Subtítulos",
     "depende_de": ["assets"], "unidades": True},
    {"id": "render", "nombre": "Render",
     "depende_de": ["callouts"], "unidades": True},
]

PASOS_POR_ID = {p["id"]: p for p in PASOS}

ESTADOS = ("bloqueado", "pendiente", "ejecutando", "listo", "obsoleto", "error")


def dependientes_de(paso_id):
    """Pasos que dependen directamente de paso_id."""
    return [p["id"] for p in PASOS if paso_id in p["depende_de"]]


def descendientes_de(paso_id):
    """Pasos aguas abajo de paso_id, en orden del DAG."""
    alcanzados = set()
    pendientes = list(dependientes_de(paso_id))
    while pendientes:
        actual = pendientes.pop(0)
        if actual in alcanzados:
            continue
        alcanzados.add(actual)
        pendientes.extend(dependientes_de(actual))
    return [p["id"] for p in PASOS if p["id"] in alcanzados]


class Estado:
    """Grafo de build persistido en <proyecto>/estado.json."""

    def __init__(self, proyecto):
        if not isinstance(proyecto, Proyecto):
            raise TypeError("Estado necesita un Proyecto")
        self.proyecto = proyecto
        self.ruta = proyecto.ruta(NOMBRE_ESTADO)
        self._lock = lock_de(self.ruta)
        self._sello = None
        self._cache = {}
        self._doc = None
        with self._lock:
            self._cargar()
            if self._doc.get("_nuevo"):
                self._doc.pop("_nuevo")
                self._guardar()

    # ------------------------------------------------------------------ E/S

    def _cargar(self):
        # estricto: si el fichero esta ahi pero no se puede leer, se propaga el
        # fallo. Tragarselo y empezar de cero borraria todo el historico en el
        # siguiente guardado, y estado.json es el unico sitio donde vive.
        try:
            doc = leer_json(self.ruta, estricto=True)
        except ValueError:
            doc = self._apartar_roto()
        if doc is not None and (not isinstance(doc, dict)
                                or not isinstance(doc.get("pasos"), dict)):
            doc = self._apartar_roto()
        nuevo = doc is None
        if nuevo:
            doc = {"version_formato": VERSION_FORMATO, "pasos": {}, "_nuevo": True}
        for paso in PASOS:
            doc["pasos"].setdefault(paso["id"], {
                "params": {},
                "activa": None,
                "firma": None,
                "salidas": {},
                "unidades": {},
                "invalidadas": [],
                "marca": None,
                "versiones": [],
            })
        self._doc = doc
        self._sello = self._sello_disco()
        self._cache = {}

    def _apartar_roto(self):
        """Guarda un estado.json ilegible a un lado en vez de sobreescribirlo."""
        marca = ahora().replace(":", "").replace("-", "")
        destino = self.proyecto.ruta(f"estado.roto.{marca}.json")
        try:
            os.replace(self.ruta, destino)
        except OSError:
            pass
        return None

    def _sello_disco(self):
        # st_ino es imprescindible: la marca de tiempo de Windows avanza a
        # saltos de ~15 ms, asi que dos escrituras seguidas del mismo tamano
        # comparten (mtime, size) y esta instancia se quedaria con datos viejos.
        # escribir_json sustituye el fichero entero, de modo que el indice NTFS
        # cambia en cada guardado y delata el cambio siempre.
        try:
            info = os.stat(self.ruta)
            return (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            return None

    def _sincronizar(self):
        """Recarga si otro proceso o hilo ha reescrito el fichero."""
        if self._sello_disco() == self._sello:
            return
        # la comprobacion va sin cerrojo (la hace cada lectura), pero la recarga
        # se hace con el, para no leer a medias de otro proceso que escribe
        with self._lock:
            if self._sello_disco() != self._sello:
                self._cargar()

    def _guardar(self):
        self._doc["actualizado"] = ahora()
        limpio = {k: v for k, v in self._doc.items() if not k.startswith("_")}
        escribir_json(self.ruta, limpio)
        self._sello = self._sello_disco()
        self._cache = {}

    def _validar(self, paso_id):
        if paso_id not in PASOS_POR_ID:
            raise ValueError(f"paso desconocido: {paso_id}")
        return PASOS_POR_ID[paso_id]

    def _datos(self, paso_id):
        self._validar(paso_id)
        self._sincronizar()
        return self._doc["pasos"][paso_id]

    # -------------------------------------------------------------- firmas

    def _params_globales(self, paso_id, propias=True):
        params = self._doc["pasos"][paso_id].get("params", {})
        fuera = {CLAVE_UNIDADES}
        if not propias:
            fuera |= set(CORRECCIONES.get(paso_id) or ())
        return {k: v for k, v in params.items() if k not in fuera}

    def _datos_unidad(self, paso_id, unidad):
        params = self._doc["pasos"][paso_id].get("params", {})
        bloque = params.get(CLAVE_UNIDADES)
        if isinstance(bloque, dict):
            return bloque.get(unidad)
        return None

    def _memo(self, clave, calcular):
        if clave not in self._cache:
            self._cache[clave] = calcular()
        return self._cache[clave]

    def _sello_salida(self, paso_id):
        """Identidad de lo que el paso produjo: version activa y firma con la que se hizo."""
        datos = self._doc["pasos"][paso_id]
        return _huella([datos.get("activa"), datos.get("firma")])

    def _sello_salida_unidad(self, paso_id, unidad):
        """Identidad de lo que el paso produjo para una unidad concreta."""
        registro = self._doc["pasos"][paso_id].get("unidades", {}).get(unidad)
        if not isinstance(registro, dict):
            return ""
        return _huella([registro.get("firma"), registro.get("salidas")])

    def _declaradas(self, paso_id):
        def calcular():
            propias = set()
            bloque = self._doc["pasos"][paso_id].get("params", {}).get(CLAVE_UNIDADES)
            if isinstance(bloque, dict):
                propias.update(str(u) for u in bloque)
            for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
                propias.update(self._declaradas(dependencia))
            return frozenset(propias)
        return self._memo(("decl", paso_id), calcular)

    def unidades_declaradas(self, paso_id):
        """Ids de unidad que aplican a un paso (propias mas heredadas del DAG)."""
        self._validar(paso_id)
        self._sincronizar()
        return sorted(self._declaradas(paso_id))

    def firma_global(self, paso_id):
        """Firma del paso ignorando cualquier dato por unidad de todo el grafo."""
        self._validar(paso_id)
        self._sincronizar()
        return self._firma_global(paso_id)

    def _firma_global(self, paso_id, propias=True):
        def calcular():
            partes = ["p:" + _huella(self._params_globales(paso_id, propias))]
            # LAS DEPENDENCIAS, SIEMPRE ENTERAS. Una correccion a mano del guion
            # no invalida al guion, pero SI a todo lo que se hizo leyendola: la
            # voz hay que regrabarla y los subtitulos rehacerlos.
            for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
                partes.append("g:" + self._firma_global(dependencia))
            return _huella(partes)
        return self._memo(("global", paso_id, propias), calcular)

    def firma_unidad(self, paso_id, unidad):
        """Firma de una unidad concreta: solo lo que afecta a esa unidad."""
        self._validar(paso_id)
        self._sincronizar()
        return self._firma_unidad(paso_id, str(unidad))

    def _firma_unidad(self, paso_id, unidad):
        def calcular():
            partes = ["g:" + self._firma_global(paso_id),
                      "d:" + _huella(self._datos_unidad(paso_id, unidad))]
            for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
                # si la dependencia no declara la unidad, ya esta cubierta por
                # firma_global; encadenar su firma completa contaminaria esta
                # unidad con cambios de otras unidades
                if unidad in self._declaradas(dependencia):
                    partes.append("u:" + self._firma_unidad(dependencia, unidad))
                    partes.append("s:" + self._sello_salida_unidad(dependencia, unidad))
            return _huella(partes)
        return self._memo(("unidad", paso_id, unidad), calcular)

    def firma(self, paso_id):
        """Firma completa del paso: params propios mas firmas de las entradas."""
        self._validar(paso_id)
        self._sincronizar()
        return self._firma(paso_id)

    def _firma(self, paso_id, propias=True):
        def calcular():
            partes = ["g:" + self._firma_global(paso_id, propias)]
            for unidad in sorted(self._declaradas(paso_id)):
                partes.append(f"u:{unidad}={self._firma_unidad(paso_id, unidad)}")
            for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
                partes.append("e:" + self._firma(dependencia))
                # el sello va solo en la firma completa, nunca en firma_global:
                # si entrara ahi, versionar UNA unidad de assets moveria la firma
                # de todas las unidades de callouts y se perderia la granularidad
                partes.append("s:" + self._sello_salida(dependencia))
            return _huella(partes)
        return self._memo(("firma", paso_id, propias), calcular)

    # --------------------------------------------------------------- lectura

    def estado_de(self, paso_id):
        """Estado derivado del paso: bloqueado|pendiente|ejecutando|listo|obsoleto|error."""
        datos = self._datos(paso_id)
        firma_actual = self._firma(paso_id)
        marca = datos.get("marca")
        # una marca deja de valer si los parametros cambiaron por debajo
        if isinstance(marca, dict) and marca.get("firma") == firma_actual:
            if marca.get("estado") in ("ejecutando", "error"):
                return marca["estado"]
        if datos.get("activa") is None:
            for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
                if self._doc["pasos"][dependencia].get("activa") is None:
                    return "bloqueado"
            return "pendiente"
        # LA FIRMA PROPIA, que no cuenta las correcciones hechas a mano sobre su
        # salida. Los planes de antes no la traen: ahi manda la de siempre.
        propia = datos.get("firma_propia")
        if propia is not None:
            if propia != self._firma(paso_id, propias=False):
                return "obsoleto"
        elif datos.get("firma") != firma_actual:
            return "obsoleto"
        if self._unidades_obsoletas(paso_id):
            return "obsoleto"
        return "listo"

    def al_dia(self, paso_id):
        """Si lo de este paso esta hecho y vigente, IGNORANDO que ahora mismo
        haya un trabajo atado a el. -> bool

        `estado_de` contesta "ejecutando" mientras corre un trabajo marcado en
        el paso, y eso es lo que hay que ENSENAR. Pero para decidir si una
        tarea hay que rehacerla no sirve: una tanda del modo light se registra
        en `assets`, asi que en cuanto arranca su propio paso deja de parecer
        "listo" y la tanda se rehace a si misma entera. Se vio el 01-09
        montando el video: la barra decia «Dando cara a personajes» con los
        nueve assets hechos desde hacia dias.

        El "error" SI cuenta: un paso que fallo no esta al dia por mucho que su
        version anterior siga cuadrando.
        """
        datos = self._datos(paso_id)
        firma_actual = self._firma(paso_id)
        marca = datos.get("marca")
        if (isinstance(marca, dict) and marca.get("firma") == firma_actual
                and marca.get("estado") == "error"):
            return False
        if datos.get("activa") is None:
            return False
        if datos.get("firma") != firma_actual:
            return False
        return not self._unidades_obsoletas(paso_id)

    def params(self, paso_id):
        """Copia de los parametros editables del paso."""
        return copy.deepcopy(self._datos(paso_id).get("params", {}))

    def mensaje(self, paso_id):
        """Ultimo mensaje asociado al paso (error o progreso), o cadena vacia."""
        marca = self._datos(paso_id).get("marca")
        if isinstance(marca, dict):
            return marca.get("mensaje", "") or ""
        return ""

    def salidas(self, paso_id):
        """Salidas registradas por la version activa del paso."""
        return copy.deepcopy(self._datos(paso_id).get("salidas", {}))

    def salidas_unidad(self, paso_id, unidad):
        """Salidas registradas para una unidad concreta."""
        registro = self._datos(paso_id).get("unidades", {}).get(str(unidad))
        return copy.deepcopy(registro.get("salidas", {})) if registro else {}

    def versiones(self, paso_id):
        """Historico de versiones del paso, de la mas antigua a la mas nueva.

        Devuelve las entradas TAL Y COMO ESTAN GUARDADAS, copiadas. Desde que el
        manifiesto de cada version vive en su propio fichero, una entrada nueva
        NO trae `unidades`: trae `n_unidades`. Quien necesite el manifiesto de
        verdad tiene que pedirlo con `manifiesto_version`, que es un fichero por
        version y se lee solo cuando hace falta.

        Rehidratarlo aqui seria deshacer el arreglo: son ~4 MB por version, y
        este metodo se llama para pintar una lista de seis campos. Quien solo
        vaya a pintar debe usar `versiones_resumen`, que ademas no copia nada.

        La copia profunda se conserva a proposito: quien pide el historico se lo
        lleva suelto del documento vivo y puede tocarlo sin que se entere.
        """
        datos = self._datos(paso_id)
        activa = datos.get("activa")
        historico = []
        for version in datos.get("versiones", []):
            ficha = copy.deepcopy(version)
            ficha["activa"] = (version.get("n") == activa)
            ficha["ruta"] = self.proyecto.ruta_paso(paso_id, version.get("n"))
            historico.append(ficha)
        return historico

    def versiones_resumen(self, paso_id):
        """Lo mismo que `versiones`, pero SIN el manifiesto de cada version.

        Es lo que necesita quien pinta el desplegable de versiones: numero,
        fecha, resumen, firma y CUANTAS unidades tenia. De las unidades solo se
        mira el recuento, y contar no obliga a copiar.

        La diferencia no es de estilo. `versiones()` hace copy.deepcopy() de
        cada entrada, y cada entrada de un paso por unidades guarda el manifiesto
        completo de sus unidades: en un video real son 296 MB copiados en cada
        peticion, ~0,9 s, para acabar quedandose con seis campos.

        Los dicts se construyen NUEVOS. Anotar 'activa' y 'ruta' sobre la entrada
        guardada -- que es lo que se ahorraria la copia -- las metería en
        self._doc, y el proximo _guardar() las escribiria en estado.json para
        siempre, con el agravante de que 'ruta' es una ruta absoluta de ESTA
        maquina y el fichero se copia entre maquinas al duplicar un proyecto.
        """
        datos = self._datos(paso_id)
        activa = datos.get("activa")
        resumen = []
        for version in datos.get("versiones", []):
            numero = version.get("n")
            resumen.append({
                "n": numero,
                "fecha": version.get("fecha", ""),
                "resumen": version.get("resumen", ""),
                "firma": version.get("firma", ""),
                "firma_propia": version.get("firma_propia"),
                "activa": numero == activa,
                "ruta": self.proyecto.ruta_paso(paso_id, numero),
                # el recuento YA HECHO: quien lo reciba no tiene que ir al
                # manifiesto, que es justo lo que se quiere evitar. Las versiones
                # migradas lo traen guardado; las de formato viejo se cuentan del
                # manifiesto que todavia llevan dentro.
                "n_unidades": (version["n_unidades"] if "n_unidades" in version
                               else len(version.get(CLAVE_UNIDADES) or {})),
            })
        return resumen

    # ------------------------------------------- manifiestos de cada version
    #
    # EL MANIFIESTO DE UNA VERSION NO VIVE EN estado.json. Cada version de un
    # paso por unidades guarda que produjo CADA una de sus unidades, y eso son
    # ~4 MB por version en un video de 240 planos. Con 73 versiones, estado.json
    # llego a 320 MB: crece como versiones x unidades y nadie lo poda. El coste
    # no es el disco, es que `_cargar` reparsea el fichero ENTERO cada vez que
    # cambia (2,3 s) y `_guardar` lo reserializa entero en cada escritura (4,7 s).
    #
    # Asi que el manifiesto va a un fichero por version, y en la entrada solo
    # queda el recuento. Se mueve SOLO el manifiesto: `params` y `salidas` del
    # historico se quedan donde estaban, porque son el 3 % del peso y el 100 %
    # del contrato (las pruebas los leen de cada version).

    # La carpeta es `CARPETA_MANIFIESTOS`, definida en `proyecto.py` porque la
    # necesitan los dos modulos (aqui para leer y escribir, y `Proyecto.duplicar`
    # para llevarsela a la copia).
    #
    # Va FUERA de `pasos/<paso>/v<N>/` a proposito: `medios.sembrar_trabajo`
    # copia la carpeta de la version activa dentro de `trabajo/`, y
    # `_recoger_trabajo` vuelca `trabajo/` en la carpeta de la version NUEVA. Un
    # manifiesto dentro de v21 acabaria dentro de v22 con pinta de correcto.

    def _ruta_manifiesto(self, paso_id, numero):
        return self.proyecto.ruta("pasos", paso_id, CARPETA_MANIFIESTOS,
                                  f"v{numero}.json")

    def manifiesto_version(self, paso_id, version):
        """Que produjo cada unidad en esa version. Acepta la entrada o su numero.

        Tres formas, y la diferencia entre ellas importa:

        - la entrada trae `unidades` -> formato VIEJO, sin migrar: se devuelve.
        - no lo trae y `n_unidades` es 0 -> la version no tenia unidades.
        - no lo trae y `n_unidades` es >0 -> el manifiesto esta en su fichero, y
          si el fichero no aparece esto LANZA.

        Ese ultimo lanzar es deliberado y es lo que separa un error ruidoso de
        una factura: quien llama es `revertir`, que mete lo que reciba en el mapa
        vivo de unidades. Devolver {} ante un fichero ausente vaciaria el mapa,
        las 240 unidades pasarian a «sin hacer» y la pantalla ofreceria regenerar
        el video entero -- sin que nada hubiera fallado a la vista.

        No hay cache a proposito. Esto solo lo lee `revertir`, que es una accion
        rara y a mano; una cache aqui tendria que vivir fuera de `self._doc`
        (porque `_guardar` filtra las claves con guion bajo SOLO en la raiz, asi
        que cualquier cosa anidada se reescribiria dentro de estado.json y el
        fichero recuperaria sus 320 MB en silencio), y no compensa el riesgo.
        """
        if not isinstance(version, dict):
            numero = version
            version = None
            for candidata in self._datos(paso_id).get("versiones", []):
                if candidata.get("n") == numero:
                    version = candidata
                    break
            if version is None:
                raise ValueError(f"{paso_id} no tiene version v{numero}")
        if CLAVE_UNIDADES in version:
            return copy.deepcopy(version[CLAVE_UNIDADES])
        if not version.get("n_unidades"):
            return {}
        esperadas = version.get("n_unidades")
        ruta = self._ruta_manifiesto(paso_id, version.get("n"))
        contenido = leer_json(ruta, estricto=True)
        if not isinstance(contenido, dict):
            raise ValueError(
                f"el manifiesto de {paso_id} v{version.get('n')} no aparece o no "
                f"se puede leer: {ruta}. La version dice tener {esperadas} "
                f"unidades, asi que NO se puede dar por vacio sin dejar el paso "
                f"como si nunca se hubiera hecho.")
        # Y QUE ESTEN TODAS. Comprobar solo el tipo deja pasar un manifiesto
        # CORTO -- una escritura interrumpida, una copia a medias, una migracion
        # con un fallo silencioso --, y un manifiesto corto es justo el caso malo:
        # `revertir` lo mete en el mapa vivo y las unidades que falten pasan a
        # «sin hacer», o sea, a que la pantalla ofrezca regenerarlas y cobrarlas.
        # El recuento se guardo al escribirlo, asi que cuadrar es gratis.
        if len(contenido) != esperadas:
            raise ValueError(
                f"el manifiesto de {paso_id} v{version.get('n')} esta incompleto: "
                f"la version dice {esperadas} unidades y el fichero trae "
                f"{len(contenido)} ({ruta}).")
        return contenido

    def _guardar_manifiesto(self, paso_id, numero, mapa):
        """Escribe el manifiesto de una version. Se llama ANTES de anotarla.

        El orden importa: un manifiesto huerfano (escrito y sin entrada que lo
        nombre) es basura inofensiva; una entrada que nombra un manifiesto que no
        existe rompe el revertido de esa version.
        """
        if not mapa:
            return
        escribir_json(self._ruta_manifiesto(paso_id, numero), mapa)

    def unidades_obsoletas(self, paso_id):
        """Ids de unidad que hay que rehacer, en vez del paso entero."""
        self._validar(paso_id)
        self._sincronizar()
        return self._unidades_obsoletas(paso_id)

    def _unidades_obsoletas(self, paso_id):
        datos = self._doc["pasos"][paso_id]
        guardadas = datos.get("unidades", {})
        invalidadas = set(datos.get("invalidadas", []))
        sucias = []
        for unidad in sorted(self._declaradas(paso_id)):
            if unidad in invalidadas:
                sucias.append(unidad)
                continue
            registro = guardadas.get(unidad)
            if not registro or registro.get("firma") != self._firma_unidad(paso_id, unidad):
                sucias.append(unidad)
        return sucias

    def unidades_producidas(self, paso_id):
        """Ids de unidad de las que el paso guarda algo producido.

        No es lo mismo que las declaradas: una unidad se declara escribiendole
        params y se produce ejecutando el paso, y las dos listas se solapan solo
        en parte. Un asset, por ejemplo, no lleva params propios hasta que
        alguien le escribe feedback, asi que existe en disco mucho antes de estar
        declarado. Preguntando solo por las declaradas no habia forma de saber
        que produjo.
        """
        self._validar(paso_id)
        self._sincronizar()
        return sorted(self._doc["pasos"][paso_id].get("unidades", {}))

    def unidades_sin_hacer(self, paso_id):
        """Declaradas de las que el paso no ha producido NADA todavia.

        Son un subconjunto de unidades_obsoletas, pero no significan lo mismo y
        confundirlas es mentir sobre el estado: 'obsoleta' es que lo que hay ya
        no corresponde a sus entradas, y 'sin hacer' es que no hay nada, ni
        viejo ni nuevo. Lo primero se rehace, lo segundo se genera por primera
        vez -- y decir 'ha quedado obsoleto' de un plano que nunca se genero
        manda a buscar un cambio aguas arriba que no ha existido.
        """
        self._validar(paso_id)
        self._sincronizar()
        guardadas = self._doc["pasos"][paso_id].get("unidades", {})
        return [unidad for unidad in self._unidades_obsoletas(paso_id)
                if not isinstance(guardadas.get(unidad), dict)]

    def resumen(self):
        """Foto completa del grafo para pintar la UI."""
        self._sincronizar()
        fichas = []
        for paso in PASOS:
            paso_id = paso["id"]
            datos = self._doc["pasos"][paso_id]
            versiones = datos.get("versiones", [])
            activa = datos.get("activa")
            fecha = ""
            for version in versiones:
                if version.get("n") == activa:
                    fecha = version.get("fecha", "")
            declaradas = sorted(self._declaradas(paso_id))
            sucias = self._unidades_obsoletas(paso_id)
            fichas.append({
                "id": paso_id,
                "nombre": paso["nombre"],
                "depende_de": list(paso["depende_de"]),
                "por_unidades": paso["unidades"],
                "estado": self.estado_de(paso_id),
                "firma": self._firma(paso_id),
                "firma_guardada": datos.get("firma"),
                "activa": activa,
                "versiones": len(versiones),
                "fecha": fecha,
                "mensaje": self.mensaje(paso_id),
                "unidades": declaradas,
                "unidades_obsoletas": sucias,
                # lo ultimo que se conservo en vez de rehacerse: un paso que
                # dice "listo" tiene que poder explicar si es porque se ejecuto
                # o porque se dio por bueno lo que ya habia
                "conservado": (datos.get("conservado") or [{}])[-1] or None,
            })
        return {
            "proyecto": self.proyecto.id,
            "nombre": self.proyecto.config.get("nombre", self.proyecto.id),
            "raiz": self.proyecto.raiz,
            "actualizado": self._doc.get("actualizado", ""),
            "pasos": fichas,
        }

    # -------------------------------------------------------------- escritura

    def _sueltos_por_unidad(self, paso_id, params, previos=None):
        """Params GLOBALES que en realidad estan indexados por unidad.

        POR QUE EXISTE
        --------------
        Un parametro que describe UN plano va en el bloque `unidades`. Si va
        suelto entra en la firma GLOBAL del paso -- y con ella en la de CADA
        unidad --, asi que decidir algo de un plano deja obsoleto el video
        entero. Ha pasado dos veces (el plan de cartelas y el de rotulos), y las
        dos costo lo mismo descubrirlo: nada falla, no hay ningun error, solo
        aparece un monton de naranja que se lee como otra cosa. La segunda vez
        se pago resellando cuarenta y nueve planos a mano.

        Un fallo que no da la cara no se arregla con una nota en un documento.
        Aqui se mira si alguna clave suelta esta indexada por unidades del paso,
        y si lo esta se levanta. Ruidoso y en el momento de guardarlo, que es
        cuando todavia se sabe quien lo escribio.

        SOLO lo que se INTRODUCE o se CAMBIA. Una clave vieja que ya estaba
        guardada -- de antes de que esto existiera, o restaurada al revertir a
        una version de entonces -- no bloquea nada: su migracion la hace la
        pantalla que la conoce, y negarse a guardar por algo que ya estaba
        dejaria el proyecto sin poder tocar nada hasta abrir esa pantalla.
        """
        if not PASOS_POR_ID[paso_id]["unidades"]:
            return {}
        previos = previos if isinstance(previos, dict) else {}
        bloque = params.get(CLAVE_UNIDADES)
        nombres = set(self._declaradas(paso_id))
        if isinstance(bloque, dict):
            nombres |= {str(u) for u in bloque}
        # 'escena:S013' se escribe muchas veces solo 'S013': la pantalla y los
        # agentes hablan de planos y el grafo de unidades. Las dos formas cuentan
        nombres |= {u.split(":", 1)[1] for u in nombres if u.startswith("escena:")}
        culpables = {}
        for clave, valor in params.items():
            if clave == CLAVE_UNIDADES or not isinstance(valor, dict):
                continue
            if clave in previos and previos[clave] == valor:
                continue
            coinciden = sorted(str(k) for k in valor if str(k) in nombres)
            if coinciden:
                culpables[clave] = coinciden
        return culpables

    def set_params(self, paso_id, params, del_propio_paso=False):
        """Fija los parametros del paso; la obsolescencia se propaga sola.

        del_propio_paso=True marca que el cambio lo trae el trabajo que esta
        corriendo (por ejemplo assets anotando que assets usa cada escena), no
        una edicion del usuario: en ese caso la foto de entradas del trabajo se
        actualiza y el resultado sigue contando como al dia.
        """
        self._validar(paso_id)
        if not isinstance(params, dict):
            raise TypeError("los params de un paso son un dict")
        with self._lock:
            self._sincronizar()
            sueltos = self._sueltos_por_unidad(
                paso_id, params, self._doc["pasos"][paso_id].get("params"))
            if sueltos:
                detalle = "; ".join(
                    f"'{clave}' esta indexado por "
                    + ", ".join(us[:3]) + ("..." if len(us) > 3 else "")
                    for clave, us in sorted(sueltos.items()))
                raise ValueError(
                    f"en '{paso_id}': {detalle}. Un parametro que describe una "
                    f"unidad va DENTRO de params['{CLAVE_UNIDADES}']"
                    f"['<unidad>'], nunca suelto: todo lo que no es ese bloque "
                    f"entra en la firma global del paso, asi que guardarlo "
                    f"dejaria obsoletas TODAS sus unidades")
            datos = self._doc["pasos"][paso_id]
            antes = self._firma(paso_id)
            if datos.get("params") == params:
                return False
            datos["params"] = copy.deepcopy(params)
            self._cache = {}
            cambiado = self._firma(paso_id) != antes
            marca = datos.get("marca")
            corriendo = isinstance(marca, dict) and marca.get("estado") == "ejecutando"
            if cambiado and corriendo and del_propio_paso:
                self._fotografiar_entradas(paso_id)
            elif cambiado and isinstance(marca, dict) and not corriendo:
                datos["marca"] = None
            # la marca de "ejecutando" ajena se conserva: es la prueba de con que
            # entradas arranco el trabajo que sigue vivo, y completar() la necesita
            self._guardar()
            return cambiado

    def actualizar_params(self, paso_id, cambios, del_propio_paso=False):
        """Mezcla cambios sobre los parametros existentes del paso."""
        self._validar(paso_id)
        # leer y escribir van dentro del MISMO cerrojo: si se lee fuera, otro
        # hilo o proceso puede guardar entre la lectura y la escritura y su
        # cambio desaparece al volcar aqui los parametros enteros
        with self._lock:
            self._sincronizar()
            params = copy.deepcopy(self._doc["pasos"][paso_id].get("params", {}))
            for clave, valor in (cambios or {}).items():
                if clave == CLAVE_UNIDADES and isinstance(valor, dict):
                    bloque = params.get(CLAVE_UNIDADES)
                    bloque = dict(bloque) if isinstance(bloque, dict) else {}
                    bloque.update(copy.deepcopy(valor))
                    params[CLAVE_UNIDADES] = bloque
                else:
                    params[clave] = copy.deepcopy(valor)
            return self.set_params(paso_id, params, del_propio_paso=del_propio_paso)

    def marcar_ejecutando(self, paso_id):
        """Marca el paso como en marcha y fotografia las entradas que usa."""
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            self._fotografiar_entradas(paso_id)
            self._guardar()

    def _fotografiar_entradas(self, paso_id):
        """Deja en la marca las entradas exactas con las que corre el trabajo.

        Si el usuario edita mientras el trabajo corre, completar() no puede
        fingir que el resultado corresponde a los parametros nuevos.
        """
        self._doc["pasos"][paso_id]["marca"] = {
            "estado": "ejecutando",
            "mensaje": "",
            "firma": self._firma(paso_id),
            "fecha": ahora(),
            "params": copy.deepcopy(self._doc["pasos"][paso_id].get("params", {})),
            "unidades": {u: self._firma_unidad(paso_id, u)
                         for u in sorted(self._declaradas(paso_id))},
        }

    def marcar_error(self, paso_id, mensaje):
        """Marca el paso como fallido; se limpia solo si cambian los params."""
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            self._doc["pasos"][paso_id]["marca"] = {
                "estado": "error",
                "mensaje": str(mensaje),
                "firma": self._firma(paso_id),
                "fecha": ahora(),
            }
            self._guardar()

    def limpiar_marca(self, paso_id):
        """Quita la marca de ejecucion o error del paso."""
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            if self._doc["pasos"][paso_id].get("marca") is not None:
                self._doc["pasos"][paso_id]["marca"] = None
                self._guardar()

    def adoptar(self, paso_id, unidades=None, motivo="", quien="analisis",
                rehacer=()):
        """Acepta las entradas nuevas SIN rehacer: lo que hay sigue valiendo.

        POR QUE EXISTE
        --------------
        La obsolescencia de este grafo se DERIVA de las firmas, y eso es lo
        correcto: nadie tiene que acordarse de marcar nada. Pero derivar tiene un
        efecto que en un video largo se paga caro: tocar una frase del guion
        cambia la firma de guion, y con ella la de voz, assets, callouts y
        render. Todo queda obsoleto aunque 170 de los 174 planos narren
        exactamente lo mismo que antes.

        Adoptar es decir, con nombre y motivo: "estas entradas son otras, pero lo
        que este paso produjo para estas unidades sigue sirviendo". Se refresca
        la firma y se deja la salida donde esta.

        QUE LO MANTIENE HONESTO
        -----------------------
          - No crea version: no se ha producido nada nuevo, y fingir una version
            haria creer que se regenero.
          - Queda escrito en 'conservado', con la firma de antes, la de despues,
            quien lo decidio y por que. Un paso que dice "listo" tiene que poder
            explicar si eso es porque se ejecuto o porque se conservo.
          - Las unidades que hay que rehacer se marcan a la vez ('rehacer'), en
            la misma operacion: conservar sin decir que NO se conserva seria
            justo la degradacion silenciosa que este sistema no se permite.

        unidades=None conserva todas las declaradas. Con una lista, solo esas.
        """
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            datos = self._doc["pasos"][paso_id]
            if datos.get("activa") is None:
                raise ValueError(f"{paso_id} no ha producido nada todavia: no hay "
                                 f"nada que conservar")
            antes = datos.get("firma")
            declaradas = sorted(self._declaradas(paso_id))
            a_rehacer = {str(u) for u in (rehacer or [])}
            objetivo = [u for u in (declaradas if unidades is None
                                    else [str(u) for u in unidades])
                        if u in set(declaradas) and u not in a_rehacer]

            mapa = copy.deepcopy(datos.get("unidades", {}))
            conservadas = []
            for unidad in objetivo:
                registro = mapa.get(unidad)
                if not isinstance(registro, dict):
                    # nunca se produjo: no hay nada que conservar, y darle la
                    # firma nueva la daria por hecha sin haberla hecho
                    continue
                registro["firma"] = self._firma_unidad(paso_id, unidad)
                registro["conservada"] = ahora()
                mapa[unidad] = registro
                conservadas.append(unidad)
            datos["unidades"] = mapa
            if a_rehacer:
                pendientes = set(datos.get("invalidadas", [])) | a_rehacer
                datos["invalidadas"] = sorted(pendientes)
            # La firma del PASO se refresca siempre: el paso acepta las entradas
            # nuevas. Que siga o no obsoleto lo decide _unidades_obsoletas, que
            # es lo que mira las unidades que quedan por rehacer.
            datos["firma"] = self._firma(paso_id)
            datos["firma_propia"] = self._firma(paso_id, propias=False)
            historico = datos.setdefault("conservado", [])
            historico.append({
                "fecha": ahora(), "motivo": str(motivo or ""), "quien": str(quien),
                "firma_antes": antes, "firma_despues": datos["firma"],
                "version": datos.get("activa"),
                "unidades": conservadas, "rehacer": sorted(a_rehacer),
            })
            del historico[:-20]
            self._guardar()
            return {"paso": paso_id, "conservadas": conservadas,
                    "rehacer": sorted(a_rehacer),
                    "estado": self.estado_de(paso_id)}

    def conservaciones(self, paso_id):
        """Historico de lo que se conservo en vez de rehacerse."""
        return copy.deepcopy(self._datos(paso_id).get("conservado", []))

    def invalidar_unidades(self, paso_id, ids):
        """Fuerza a rehacer unidades concretas sin tocar el resto del paso."""
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            datos = self._doc["pasos"][paso_id]
            invalidadas = set(datos.get("invalidadas", []))
            invalidadas.update(str(u) for u in (ids or []))
            datos["invalidadas"] = sorted(invalidadas)
            self._guardar()
            return sorted(invalidadas)

    def retirar_unidades(self, paso_id, ids, motivo=""):
        """Des-declara unidades que YA NO EXISTEN. Lo contrario de invalidar.

        Invalidar dice "esta hay que rehacerla". Esto dice "esta ya no es de
        nadie": el plano S026 desaparecio del guion y no lo va a producir nunca
        nadie mas.

        Sin esto, el paso se quedaba OBSOLETO PARA SIEMPRE. Los ids de plano son
        posicionales y se heredan entre planes; cuando un recorte nuevo deja
        fuera un plano, `_heredar_ids` lo pone en 'retirados' pero su unidad
        seguia DECLARADA en params. `completar()` solo refresca la firma de las
        unidades que la pasada ha producido, asi que la del plano retirado se
        quedaba vieja, `unidades_obsoletas` la seguia contando, y no habia
        ninguna forma de quitarla desde la interfaz: rehacer no la tocaba porque
        el plan ya no la incluye. Un paso terminado del todo seguia en ambar.

        Se deja constancia en el mismo historico que `adoptar`, y por el mismo
        motivo: des-declarar tambien es una decision, y una decision que no se
        puede explicar despues es la que acaba dando miedo tocar.

        Y si el paso estaba AL DIA, sigue estandolo: ver el comentario de la
        firma, ahi abajo. Retirar no puede ser otra forma de dejarlo en ambar.
        """
        self._validar(paso_id)
        fuera = sorted({str(u) for u in (ids or []) if str(u)})
        if not fuera:
            return {"paso": paso_id, "retiradas": []}
        with self._lock:
            self._sincronizar()
            datos = self._doc["pasos"][paso_id]
            declaradas = dict((datos.get("params") or {}).get(CLAVE_UNIDADES) or {})
            producidas = dict(datos.get("unidades") or {})
            quitadas = [u for u in fuera if u in declaradas or u in producidas]
            if not quitadas:
                return {"paso": paso_id, "retiradas": []}
            # SI EL PASO ESTABA AL DIA, TIENE QUE SEGUIR ESTANDOLO. Se mira
            # ANTES de quitar nada, que es lo que hace segura la linea de abajo.
            estaba_al_dia = datos.get("firma") == self._firma(paso_id)
            for unidad in quitadas:
                declaradas.pop(unidad, None)
                producidas.pop(unidad, None)
            datos.setdefault("params", {})[CLAVE_UNIDADES] = declaradas
            datos["unidades"] = producidas
            datos["invalidadas"] = sorted(set(datos.get("invalidadas", [])) - set(quitadas))
            self._cache = {}          # las declaradas han cambiado: a recalcular
            # LA FIRMA SOLO SE RESELLA SI YA CUADRABA, y ni una vez mas.
            #
            # Aqui ponia que la firma NO se toca nunca, y el motivo era bueno:
            # `self._firma()` la recalcula contra lo que hay AHORA aguas arriba,
            # asi que si el guion se re-versiono mientras corria la tanda,
            # resellar a ciegas sellaria una firma con la que el paso no ha
            # corrido nunca y taparia una obsolescencia de verdad.
            #
            # Pero no tocarla nunca tenia su propio precio, y se vio en cuanto
            # el fundido empezo a retirar unidades de verdad:
            # la firma del paso incluye la lista de unidades DECLARADAS, asi que
            # quitar una la mueve por si sola. El paso quedaba en ambar con CERO
            # unidades sucias -- «obsoleto, nada que rehacer» -- y la unica cura
            # era volver a ejecutarlo, que es exactamente el estado que esta
            # funcion existe para evitar.
            #
            # La condicion resuelve las dos cosas: si cuadraba, retirar no puede
            # descuadrarla (lo que el paso produjo con sus entradas no ha
            # cambiado: solo ha dejado de declarar algo que ya no existe); y si
            # NO cuadraba, se queda como estaba y la obsolescencia de verdad
            # sigue viendose.
            if estaba_al_dia:
                datos["firma"] = self._firma(paso_id)
            datos["firma_propia"] = self._firma(paso_id, propias=False)
            historico = datos.setdefault("retirado", [])
            historico.append({
                "fecha": ahora(), "motivo": str(motivo or "ya no estan en el plan"),
                "unidades": quitadas, "version": datos.get("activa"),
            })
            del historico[:-20]
            self._guardar()
            return {"paso": paso_id, "retiradas": quitadas,
                    "estado": self.estado_de(paso_id)}

    def retiradas(self, paso_id):
        """Historico de unidades des-declaradas por desaparecer del plan.

        Va aparte del de `conservaciones`, y no por orden: ese historico es el
        que alimenta el cartel de «Conservado, no regenerado» de la pantalla, y
        meter aqui las retiradas hacia que ese cartel contara una decision que
        no es la suya -- decia «0 unidades se dieron por buenas» encima de una
        retirada, que no es ni lo uno ni lo otro.
        """
        return copy.deepcopy(self._datos(paso_id).get("retirado", []))

    def completar(self, paso_id, salidas, unidades=None):
        """Crea una version nueva con las salidas del paso y la activa."""
        self._validar(paso_id)
        if salidas is None:
            salidas = {}
        if not isinstance(salidas, dict):
            raise TypeError("las salidas de un paso son un dict")
        if unidades is not None and not isinstance(unidades, dict):
            raise TypeError("unidades es None o un dict {id_unidad: salidas}")
        with self._lock:
            self._sincronizar()
            datos = self._doc["pasos"][paso_id]
            numero = max([v.get("n", 0) for v in datos.get("versiones", [])] or [0]) + 1
            destino = self.proyecto.ruta_paso(paso_id, numero, crear=True)
            self._recoger_trabajo(paso_id, destino)

            # si el trabajo arranco con marcar_ejecutando, lo que se guarda son
            # LAS ENTRADAS CON LAS QUE CORRIO, no las de ahora: asi un trabajo
            # largo que termina despues de que el usuario edite deja el paso
            # obsoleto en vez de declararse al dia con material viejo
            marca = datos.get("marca")
            arranque = marca if isinstance(marca, dict) and marca.get("estado") == "ejecutando" else None
            firmas_arranque = arranque.get("unidades", {}) if arranque else {}
            params_version = copy.deepcopy(arranque["params"]) if arranque and "params" in arranque \
                else copy.deepcopy(datos.get("params", {}))

            declaradas = set(self._declaradas(paso_id))
            objetivo = set(str(u) for u in unidades) if unidades is not None else declaradas
            mapa = copy.deepcopy(datos.get("unidades", {}))
            for unidad in sorted(objetivo):
                previo = mapa.get(unidad) if isinstance(mapa.get(unidad), dict) else {}
                if unidades is not None:
                    valor = unidades.get(unidad)
                    salidas_unidad = copy.deepcopy(valor) if isinstance(valor, dict) else {"valor": valor}
                else:
                    # sin mapa explicito el paso no ha dicho nada de sus unidades:
                    # refrescar la firma si, borrar lo que produjeron no
                    salidas_unidad = copy.deepcopy(previo.get("salidas", {}))
                mapa[unidad] = {
                    "firma": firmas_arranque.get(unidad) or self._firma_unidad(paso_id, unidad),
                    "fecha": ahora(),
                    "salidas": salidas_unidad,
                }
            # EL MANIFIESTO PRIMERO, ANTES DE TOCAR NADA DE `datos`.
            #
            # El orden es la unica proteccion que hay aqui, y hace falta desde
            # que el manifiesto salio de estado.json. Antes los dos vivian en el
            # MISMO fichero, asi que lo que impedia guardar el manifiesto impedia
            # guardar el documento y un estado a medias no podia llegar al disco.
            # Ahora son dos ficheros: si esto falla despues de haber puesto
            # `datos["activa"] = numero`, la excepcion sube, el gestor de trabajos
            # llama a `marcar_error`, y SU `_guardar()` si funciona -- dejando en
            # disco un `activa: N` con `versiones` sin la N. Eso no se ve como un
            # fallo: el desplegable no marca ninguna version activa, «Revertir a
            # la N» da 404, y la pantalla ensena las imagenes de la version
            # ANTERIOR como si fueran las que se acaban de pagar.
            #
            # Escribiendolo aqui, un fallo deja el documento vivo intacto: la
            # tanda se pierde, que es lo de siempre, pero el estado no miente.
            self._guardar_manifiesto(paso_id, numero, mapa)

            datos["unidades"] = mapa
            datos["invalidadas"] = sorted(set(datos.get("invalidadas", [])) - objetivo)
            datos["salidas"] = copy.deepcopy(salidas)
            datos["firma"] = arranque["firma"] if arranque else self._firma(paso_id)
            datos["firma_propia"] = self._firma(paso_id, propias=False)
            datos["activa"] = numero
            datos["marca"] = None
            datos.setdefault("versiones", []).append({
                "n": numero,
                "fecha": ahora(),
                "firma": datos["firma"],
                "firma_propia": datos.get("firma_propia"),
                "resumen": self._resumen_version(paso_id, salidas, objetivo),
                "params": params_version,
                "salidas": copy.deepcopy(salidas),
                # el RECUENTO, no el manifiesto: es lo unico que se lee de aqui
                # para pintar, y el manifiesto entero ya esta en su fichero
                "n_unidades": len(mapa),
            })
            self.proyecto.fijar_version_activa(paso_id, numero)
            self._guardar()
            return numero

    def revertir(self, paso_id, version):
        """Activa una version anterior; nada se borra y aguas abajo se recalcula."""
        self._validar(paso_id)
        with self._lock:
            self._sincronizar()
            datos = self._doc["pasos"][paso_id]
            elegida = None
            for candidata in datos.get("versiones", []):
                if candidata.get("n") == int(version):
                    elegida = candidata
            if elegida is None:
                raise ValueError(f"{paso_id} no tiene version v{version}")
            # revertir tambien restaura los params de esa version: son parte de
            # la entrada con la que se produjo, y sin ellos la firma mentiria
            datos["params"] = copy.deepcopy(elegida.get("params", {}))
            # el manifiesto puede estar en la entrada (formato viejo) o en su
            # fichero. `manifiesto_version` distingue los dos casos y LANZA si la
            # version dice tener unidades y el fichero no aparece: lo que aqui se
            # meta pasa a ser el mapa vivo, y meter {} por error dejaria las 240
            # unidades como «sin hacer», o sea, ofreciendo regenerar el video
            datos[CLAVE_UNIDADES] = self.manifiesto_version(paso_id, elegida)
            datos["salidas"] = copy.deepcopy(elegida.get("salidas", {}))
            datos["firma"] = elegida.get("firma")
            # una version de antes no guarda la propia: se recalcula, que es lo
            # mismo que hacia el sistema entero antes de que existiera
            datos["firma_propia"] = (elegida.get("firma_propia")
                                     or self._firma(paso_id, propias=False))
            datos["activa"] = elegida.get("n")
            # las unidades marcadas a mano siguen pendientes: son una orden del
            # revisor sobre el paso, no sobre una version concreta, y borrarlas
            # aqui haria que una unidad rechazada volviese a figurar como buena
            datos["invalidadas"] = sorted(set(datos.get("invalidadas", []))
                                          & set(self._declaradas(paso_id)))
            datos["marca"] = None
            self.proyecto.fijar_version_activa(paso_id, elegida.get("n"))
            self._guardar()

    # --------------------------------------------------------------- interno

    def _recoger_trabajo(self, paso_id, destino):
        """Mueve lo que el paso dejo en trabajo/ dentro de la version nueva.

        Lo hace con `recolocar`, que insiste y, si un fichero sigue abierto por
        otro proceso, copia en vez de mover. Esto es lo ULTIMO que pasa despues
        de una generacion de assets de veinte minutos, y con la pantalla de ese
        paso abierta el navegador tiene pedidos justo los PNG de trabajo/: un
        [WinError 32] aqui tiraba la version entera --y a medio camino-- por no
        poder cambiar de carpeta un trabajo que ya estaba hecho y pagado.
        """
        origen = self.proyecto.ruta_trabajo(paso_id, crear=False)
        if not os.path.isdir(origen):
            return
        for nombre in os.listdir(origen):
            recolocar(os.path.join(origen, nombre),
                      os.path.join(destino, nombre))
        # Lo que no se haya podido soltar se queda, y es inofensivo por
        # construccion: `recolocar` solo deja el origen cuando ya ha copiado ese
        # mismo fichero en la version nueva, asi que lo que sobrevive en
        # trabajo/ es byte a byte lo que se acaba de versionar.
        shutil.rmtree(origen, ignore_errors=True)

    def _resumen_version(self, paso_id, salidas, objetivo):
        if isinstance(salidas, dict) and salidas.get("resumen"):
            return str(salidas["resumen"])
        if PASOS_POR_ID[paso_id]["unidades"]:
            return f"{len(objetivo)} unidades: " + ", ".join(sorted(objetivo)[:8])
        claves = ", ".join(sorted(k for k in salidas)) if salidas else "sin salidas"
        return claves
