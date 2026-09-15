"""
Trabajos en segundo plano del Estudio de Video.

Cada trabajo corre en su propio hilo. La funcion recibe como PRIMER argumento
un callable 'avisar(valor, mensaje, publico)' con el que reporta progreso; si el
trabajo se cancela, la siguiente llamada a avisar lanza Cancelado y el hilo
termina.

DOS MENSAJES Y NO UNO. `mensaje` es el de casa: dice exactamente que esta
pasando, con sus cifras y sus nombres, y es lo que lee el modo editor y lo que
queda en la bitacora. `publico` es como se cuenta lo mismo cuando la pantalla se
esta GRABANDO -- el modo light se ensena-- y por eso viaja aparte en vez de
sustituirlo: enmascarar el unico mensaje que hay dejaria al modo editor sin
saber por donde va, y a la bitacora sin nada que investigar. Quien lo escribe es
quien conoce la tarea (app.py, con `recetas.publico_de`); aqui solo se guarda y
se sirve.

    gestor = GestorTrabajos(estado=estado, bitacora=bitacora)

    def sintetizar(avisar, plan):
        avisar(0.1, "pidiendo audio")
        ...
        return {"wav": ruta}

    tid = gestor.lanzar("voz", sintetizar, plan, paso="voz")
    gestor.estado(tid)   -> {"estado": "ejecutando", "progreso": 0.1, ...}
"""
import threading
import time
import traceback
import uuid


class Cancelado(Exception):
    """Se lanza dentro del trabajo cuando alguien pide cancelarlo."""


class GestorTrabajos:
    """Lanza funciones en hilos y expone su progreso de forma consultable."""

    def __init__(self, estado=None, bitacora=None, retencion=200):
        self.estado_grafo = estado
        self.bitacora = bitacora
        self.retencion = int(retencion)
        self._trabajos = {}
        self._orden = []
        self._hilos = {}
        self._lock = threading.RLock()

    def lanzar(self, nombre, funcion, *args, paso=None, unidad=None,
               unidades=None, **kwargs):
        """Arranca un trabajo en segundo plano y devuelve su identificador."""
        if not callable(funcion):
            raise TypeError("funcion debe ser invocable")
        trabajo_id = uuid.uuid4().hex[:12]
        registro = {
            "id": trabajo_id,
            "nombre": str(nombre),
            "paso": paso,
            "unidad": unidad,
            # QUE SE ESTA REHACIENDO, para que la pantalla lo pueda retomar. Sin
            # esto, recargar a media regeneracion perdia de vista que plano iba:
            # el trabajo seguia corriendo en el servidor y la tarjeta volvia a
            # decir «Regenerar imagen», como si no hubiera nada en marcha.
            "unidades": [str(u) for u in (unidades or [])],
            "estado": "pendiente",
            "progreso": 0.0,
            "mensaje": "",
            "publico": "",
            "resultado": None,
            "error": None,
            "inicio": time.time(),
            "fin": None,
            "cancelar": False,
        }
        with self._lock:
            self._trabajos[trabajo_id] = registro
            self._orden.append(trabajo_id)
            self._podar()
        hilo = threading.Thread(
            target=self._correr,
            args=(trabajo_id, funcion, args, kwargs),
            name=f"trabajo-{nombre}-{trabajo_id}",
            daemon=True,
        )
        with self._lock:
            self._hilos[trabajo_id] = hilo
        hilo.start()
        return trabajo_id

    def progreso(self, trabajo_id, valor, mensaje="", publico=""):
        """Actualiza el progreso; lanza Cancelado si se pidio cancelar.

        `publico` es opcional: quien no lo mande deja el anterior, igual que con
        `mensaje`. Un hueco es preferible a un parpadeo, y un mensaje publico
        viejo sigue siendo publico.
        """
        with self._lock:
            registro = self._trabajos.get(trabajo_id)
            if registro is None:
                raise KeyError(f"trabajo desconocido: {trabajo_id}")
            if registro["cancelar"]:
                raise Cancelado(registro.get("mensaje") or "cancelado")
            try:
                valor = float(valor)
            except (TypeError, ValueError):
                valor = registro["progreso"]
            registro["progreso"] = max(0.0, min(1.0, valor))
            if mensaje:
                registro["mensaje"] = str(mensaje)
            if publico:
                registro["publico"] = str(publico)
        return registro["progreso"]

    def estado(self, trabajo_id):
        """Foto del trabajo: estado, progreso, mensaje, resultado, error, segundos."""
        with self._lock:
            registro = self._trabajos.get(trabajo_id)
            if registro is None:
                raise KeyError(f"trabajo desconocido: {trabajo_id}")
            return self._ficha(registro)

    def listar(self, activos=True):
        """Trabajos conocidos, del mas reciente al mas antiguo."""
        with self._lock:
            fichas = [self._ficha(self._trabajos[t]) for t in reversed(self._orden)
                      if t in self._trabajos]
        if activos:
            fichas = [f for f in fichas if f["estado"] in ("pendiente", "ejecutando")]
        return fichas

    def cancelar(self, trabajo_id):
        """Pide la cancelacion cooperativa del trabajo."""
        with self._lock:
            registro = self._trabajos.get(trabajo_id)
            if registro is None:
                raise KeyError(f"trabajo desconocido: {trabajo_id}")
            if registro["estado"] in ("listo", "error", "cancelado"):
                return False
            registro["cancelar"] = True
            if registro["estado"] == "pendiente":
                registro["estado"] = "cancelado"
                registro["fin"] = time.time()
            return True

    def esperar(self, trabajo_id, tiempo_max=None):
        """Bloquea hasta que el trabajo acabe y devuelve su ficha final."""
        with self._lock:
            hilo = self._hilos.get(trabajo_id)
        if hilo is not None:
            hilo.join(tiempo_max)
        return self.estado(trabajo_id)

    # --------------------------------------------------------------- interno

    def _ficha(self, registro):
        fin = registro["fin"] or time.time()
        return {
            "id": registro["id"],
            "nombre": registro["nombre"],
            "paso": registro["paso"],
            "unidad": registro["unidad"],
            "unidades": list(registro.get("unidades") or []),
            "estado": registro["estado"],
            "progreso": round(registro["progreso"], 4),
            "mensaje": registro["mensaje"],
            "publico": registro["publico"],
            "resultado": registro["resultado"],
            "error": registro["error"],
            "segundos": round(fin - registro["inicio"], 2),
        }

    def _podar(self):
        """Olvida los trabajos terminados mas antiguos por encima de retencion."""
        if len(self._orden) <= self.retencion:
            return
        sobran = len(self._orden) - self.retencion
        vivos = []
        for trabajo_id in self._orden:
            registro = self._trabajos.get(trabajo_id)
            terminado = registro and registro["estado"] in ("listo", "error", "cancelado")
            if sobran > 0 and terminado:
                self._trabajos.pop(trabajo_id, None)
                self._hilos.pop(trabajo_id, None)
                sobran -= 1
                continue
            vivos.append(trabajo_id)
        self._orden = vivos

    def _fijar(self, trabajo_id, **campos):
        with self._lock:
            registro = self._trabajos.get(trabajo_id)
            if registro is not None:
                registro.update(campos)

    def _correr(self, trabajo_id, funcion, args, kwargs):
        with self._lock:
            registro = self._trabajos.get(trabajo_id)
            if registro is None or registro["cancelar"]:
                if registro is not None:
                    registro["estado"] = "cancelado"
                    registro["fin"] = time.time()
                return
            registro["estado"] = "ejecutando"
            paso = registro["paso"]
            nombre = registro["nombre"]
            unidad = registro["unidad"]

        if paso and self.estado_grafo is not None:
            self.estado_grafo.marcar_ejecutando(paso)
        if self.bitacora is not None:
            self.bitacora.anotar("trabajo_lanzado", paso, {"trabajo": nombre,
                                                          "id": trabajo_id}, unidad)

        def avisar(valor, mensaje="", publico=""):
            return self.progreso(trabajo_id, valor, mensaje, publico)

        try:
            resultado = funcion(avisar, *args, **kwargs)
        except Cancelado:
            self._fijar(trabajo_id, estado="cancelado", fin=time.time(),
                        mensaje="cancelado", publico="cancelado")
            if paso and self.estado_grafo is not None:
                self.estado_grafo.limpiar_marca(paso)
            if self.bitacora is not None:
                self.bitacora.anotar("trabajo_cancelado", paso,
                                     {"trabajo": nombre, "id": trabajo_id}, unidad)
            return
        except Exception as fallo:
            detalle = traceback.format_exc(limit=6)
            self._fijar(trabajo_id, estado="error", fin=time.time(),
                        error=f"{type(fallo).__name__}: {fallo}", mensaje=str(fallo))
            if paso and self.estado_grafo is not None:
                self.estado_grafo.marcar_error(paso, f"{type(fallo).__name__}: {fallo}")
            if self.bitacora is not None:
                self.bitacora.anotar("trabajo_fallido", paso,
                                     {"trabajo": nombre, "id": trabajo_id,
                                      "error": str(fallo), "traza": detalle}, unidad)
            return

        self._fijar(trabajo_id, estado="listo", fin=time.time(), progreso=1.0,
                    resultado=resultado)
        # si la funcion no llamo a completar(), el paso se quedaria marcado
        # como ejecutando para siempre: se limpia la marca por si acaso
        if paso and self.estado_grafo is not None:
            self.estado_grafo.limpiar_marca(paso)
        if self.bitacora is not None:
            self.bitacora.anotar("trabajo_terminado", paso,
                                 {"trabajo": nombre, "id": trabajo_id}, unidad)
