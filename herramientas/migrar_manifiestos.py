"""Saca el manifiesto de unidades de cada version fuera de estado.json.

Cada version de un paso por unidades guardaba, DENTRO de estado.json, el
manifiesto completo de todas sus unidades. Con 73 versiones de 240 planos eso
son 296 MB en un fichero que `_cargar` reparsea entero cada vez que cambia
(2,3 s) y que `_guardar` reserializa entero en cada escritura (4,7 s).

Esta herramienta mueve esos manifiestos a `pasos/<paso>/_versiones/v<N>.json` y
deja en la entrada solo el recuento (`n_unidades`).

    python herramientas/migrar_manifiestos.py <raiz_de_proyectos>
    python herramientas/migrar_manifiestos.py <raiz_de_proyectos> --aplicar

Sin --aplicar es un simulacro: no escribe nada y dice cuanto se ahorraria.

EL CODIGO NUEVO PRIMERO, LOS DATOS DESPUES. No es una preferencia de orden: el
codigo viejo lee el manifiesto con `elegida.get("unidades", {})`, asi que sobre
datos ya migrados un «Revertir» se encuentra {} y VACIA el mapa vivo de unidades
-- las 232 pasan a «sin hacer» y la pantalla ofrece regenerar el video entero,
sin un solo error. Por lo mismo, una vez migrado NO se puede volver atras el
codigo sin restaurar tambien los estado.json.

PARA LOS SERVICIOS ANTES DE APLICARLA. Tampoco es opcional: el cerrojo de
ficheros vive en `tempfile.gettempdir()` y las unidades de systemd llevan
`PrivateTmp=yes`, asi que un migrador lanzado desde fuera cree tomar exclusion
mutua y no toma nada. Como `escribir_json` es atomico nunca veria un fichero a
medias: escribiria ENCIMA de una tanda de veinte minutos y la revertiria sin un
solo mensaje -- y la validacion de aqui la certificaria como correcta, porque
compara contra lo que leyo al empezar.

Y LANZALA COMO EL USUARIO QUE POSEE LOS DATOS (`sudo -u studio -E`). Lanzada como
root, `escribir_json` deja los ficheros en 0600 de root y las carpetas en 0755:
el servicio no puede ni LEER el estado.json reescrito (revienta en la siguiente
peticion) y no puede ESCRIBIR en `_versiones/`, asi que el siguiente `completar`
falla despues de haber generado y pagado las imagenes. Si ya se ha lanzado mal,
no basta con arreglar el estado.json: hace falta
`chown -R studio:studio <proyectos>` sobre estado.json Y sobre todos los
`pasos/*/_versiones/`.

Que hace, por proyecto:
  1. copia de rescate FRESCA de estado.json (para poder deshacer esta pasada) y,
     la primera vez, una copia de archivo en estado.antes-manifiestos.json
  2. escribe un manifiesto por version que lo lleve dentro
  3. reescribe estado.json sin los manifiestos y con el recuento
  4. VALIDA: relee y comprueba que el manifiesto de CADA version se recupera
     identico. Si algo no cuadra, deshace (de forma atomica) y deja el proyecto
     exactamente como estaba.
"""
import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo.proyecto import CARPETA_MANIFIESTOS, escribir_json, leer_json  # noqa: E402

ARCHIVO = "estado.antes-manifiestos.json"
RESCATE = ".estado.rescate.json"
#: Hasta donde se baja buscando proyectos. 2 alcanza `_papelera/<proyecto>`, que
#: es un proyecto de verdad y tiene que migrarse con los demas: si se queda
#: atras, restaurarlo mas adelante mete datos de formato viejo (que se leen bien)
#: pero deja la carpeta a medio migrar sin que nadie lo diga.
HONDURA = 2


def canonico(valor):
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)


def ruta_manifiesto(raiz_proyecto, paso_id, numero):
    return os.path.join(raiz_proyecto, "pasos", str(paso_id),
                        CARPETA_MANIFIESTOS, "v%s.json" % numero)


def restaurar(origen, destino):
    """Deja `destino` con el contenido de `origen`, de forma ATOMICA.

    Con `shutil.copy2` el deshacer seria la unica escritura del flujo que puede
    dejar un fichero a medias: se corta la copia de un estado.json de 320 MB y el
    proyecto se queda sin estado legible, que es peor que el fallo que se estaba
    intentando deshacer.
    """
    carpeta = os.path.dirname(os.path.abspath(destino))
    descriptor, temporal = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
    os.close(descriptor)
    try:
        shutil.copyfile(origen, temporal)
        os.replace(temporal, destino)
    except BaseException:
        if os.path.exists(temporal):
            os.remove(temporal)
        raise


def versiones_de(doc):
    """[(paso, entrada)] de todo el historico, en orden."""
    for paso_id, datos in (doc.get("pasos") or {}).items():
        if not isinstance(datos, dict):
            continue
        for version in (datos.get("versiones") or []):
            if isinstance(version, dict):
                yield paso_id, version


def revisar_migrado(raiz_proyecto, doc):
    """Problemas de un proyecto que se declara ya migrado. Lista vacia = bien."""
    problemas = []
    for paso_id, version in versiones_de(doc):
        if "unidades" in version:
            continue
        esperadas = version.get("n_unidades") or 0
        if not esperadas:
            continue
        ruta = ruta_manifiesto(raiz_proyecto, paso_id, version.get("n"))
        contenido = leer_json(ruta)
        if not isinstance(contenido, dict):
            problemas.append("%s v%s sin manifiesto" % (paso_id, version.get("n")))
        elif len(contenido) != esperadas:
            problemas.append("%s v%s incompleto (%d de %d)"
                             % (paso_id, version.get("n"), len(contenido), esperadas))
    return problemas


def migrar(raiz_proyecto, aplicar):
    ruta_estado = os.path.join(raiz_proyecto, "estado.json")
    if not os.path.isfile(ruta_estado):
        return None
    antes = os.path.getsize(ruta_estado)
    nombre = os.path.relpath(raiz_proyecto, migrar.base)
    ficha = {"nombre": nombre, "antes": antes, "despues": antes,
             "versiones": 0, "unidades": 0}
    try:
        doc = leer_json(ruta_estado, estricto=True)
    except ValueError as fallo:
        ficha["aviso"] = "estado.json ilegible: %s" % fallo
        return ficha
    if not isinstance(doc, dict) or not isinstance(doc.get("pasos"), dict):
        ficha["aviso"] = "estado.json sin la forma esperada"
        return ficha

    # DOS VERSIONES CON EL MISMO NUMERO comparten fichero de manifiesto: la
    # segunda pisa a la primera y la validacion no puede verlo (compara contra lo
    # que quedo). No deberia pasar nunca, y por eso se para en vez de apanarlo.
    pendientes = {}
    for paso_id, version in versiones_de(doc):
        if "unidades" not in version:
            continue
        clave = (paso_id, version.get("n"))
        if clave in pendientes:
            ficha["aviso"] = "%s tiene dos versiones con n=%s" % clave
            return ficha
        pendientes[clave] = version["unidades"]

    ficha["versiones"] = len(pendientes)
    ficha["unidades"] = sum(len(m or {}) for m in pendientes.values())

    if not pendientes:
        # «ya migrado» NO se declara a ojo: la herramienta que existe para no
        # perder manifiestos tiene que mirar si estan
        problemas = revisar_migrado(raiz_proyecto, doc)
        ficha["nota"] = ("ya migrado" if not problemas
                         else "MIGRADO PERO INCOMPLETO: " + "; ".join(problemas[:3]))
        if problemas:
            ficha["aviso"] = ficha.pop("nota")
        return ficha

    if not aplicar:
        copia = json.loads(json.dumps(doc))
        for _paso, version in versiones_de(copia):
            if "unidades" in version:
                version["n_unidades"] = len(version.pop("unidades") or {})
        ficha["despues"] = len(json.dumps(
            copia, ensure_ascii=False, indent=2).encode("utf-8"))
        return ficha

    # 1. LA COPIA DE RESCATE SE REFRESCA EN CADA PASADA. Reutilizar la de la
    #    primera vez haria que un fallo hoy restaurase el estado de hace semanas,
    #    perdiendo todo lo trabajado en medio: el deshacer tiene que devolver el
    #    proyecto a como estaba AL EMPEZAR ESTA pasada, no a como estaba nunca.
    rescate = os.path.join(raiz_proyecto, RESCATE)
    restaurar(ruta_estado, rescate)
    archivo = os.path.join(raiz_proyecto, ARCHIVO)
    if not os.path.exists(archivo):
        restaurar(ruta_estado, archivo)

    escritos = []
    try:
        # 2. LOS MANIFIESTOS PRIMERO. Un manifiesto huerfano es basura
        #    inofensiva; una entrada que nombra un manifiesto que no existe rompe
        #    el revertido de esa version.
        for clave in sorted(pendientes, key=lambda c: (str(c[0]), c[1] or 0)):
            mapa = pendientes[clave]
            if not mapa:
                continue
            destino = ruta_manifiesto(raiz_proyecto, clave[0], clave[1])
            escribir_json(destino, mapa)
            escritos.append(destino)

        # 3. y ahora estado.json sin ellos
        for _paso, version in versiones_de(doc):
            if "unidades" in version:
                version["n_unidades"] = len(version.pop("unidades") or {})
        escribir_json(ruta_estado, doc)

        # 4. VALIDACION: cada manifiesto de antes se recupera IDENTICO
        revisado = leer_json(ruta_estado, estricto=True)
        vistas = {(p, v.get("n")): v for p, v in versiones_de(revisado)}
        for clave, esperado in pendientes.items():
            entrada = vistas.get(clave)
            if entrada is None:
                raise ValueError("%s v%s: la version ha desaparecido" % clave)
            if "unidades" in entrada:
                raise ValueError("%s v%s: el manifiesto sigue dentro" % clave)
            if entrada.get("n_unidades") != len(esperado or {}):
                raise ValueError("%s v%s: el recuento no cuadra" % clave)
            if not esperado:
                continue
            recuperado = leer_json(ruta_manifiesto(raiz_proyecto, clave[0], clave[1]),
                                   estricto=True)
            if canonico(recuperado) != canonico(esperado):
                raise ValueError("%s v%s: el manifiesto NO es identico" % clave)
    except BaseException as fallo:
        restaurar(rescate, ruta_estado)
        for ruta in escritos:
            try:
                os.remove(ruta)
            except OSError:
                pass
        # Ctrl-C SE OBEDECE. Sin esto se deshace este proyecto y se sigue con el
        # siguiente: hay que pulsar una vez por proyecto para parar algo que esta
        # reescribiendo 320 MB de estado, que es lo ultimo que uno quiere.
        if isinstance(fallo, (KeyboardInterrupt, SystemExit)):
            raise
        ficha["error"] = "%s: %s (REVERTIDO)" % (type(fallo).__name__, fallo)
        return ficha

    os.remove(rescate)
    ficha["despues"] = os.path.getsize(ruta_estado)
    return ficha


def proyectos_en(base, hondura=HONDURA):
    """Carpetas con estado.json, hasta `hondura` niveles (para la papelera)."""
    encontrados = []
    def bajar(carpeta, nivel):
        try:
            hijos = sorted(os.listdir(carpeta))
        except OSError:
            return
        for nombre in hijos:
            ruta = os.path.join(carpeta, nombre)
            if not os.path.isdir(ruta):
                continue
            if os.path.isfile(os.path.join(ruta, "estado.json")):
                encontrados.append(ruta)
            elif nivel < hondura:
                bajar(ruta, nivel + 1)
    bajar(base, 1)
    return encontrados


def main():
    parser = argparse.ArgumentParser(
        description="Saca los manifiestos de version fuera de estado.json.")
    parser.add_argument("raiz", help="carpeta que contiene los proyectos")
    parser.add_argument("--aplicar", action="store_true",
                        help="escribir de verdad (sin esto es un simulacro)")
    args = parser.parse_args()

    if not os.path.isdir(args.raiz):
        print("no existe: %s" % args.raiz)
        return 2
    migrar.base = os.path.abspath(args.raiz)
    print("%s sobre %s\n" % ("APLICANDO" if args.aplicar
                             else "SIMULACRO (no se escribe nada)", args.raiz))
    print("%-42s%14s%14s%6s%8s  %s"
          % ("proyecto", "antes", "despues", "vers", "unid", "nota"))
    print("-" * 104)

    total_antes = total_despues = problemas = 0
    for raiz in proyectos_en(migrar.base):
        ficha = migrar(raiz, args.aplicar)
        if ficha is None:
            continue
        nota = ficha.get("error") or ficha.get("aviso") or ficha.get("nota", "")
        if ficha.get("error") or ficha.get("aviso"):
            problemas += 1
        total_antes += ficha["antes"]
        total_despues += ficha["despues"]
        print("%-42s%14s%14s%6s%8s  %s"
              % (ficha["nombre"][:41], format(ficha["antes"], ","),
                 format(ficha["despues"], ","), ficha["versiones"],
                 ficha["unidades"], nota))
    print("-" * 104)
    ahorro = total_antes - total_despues
    resumen = "%-42s%14s%14s" % ("TOTAL", format(total_antes, ","),
                                 format(total_despues, ","))
    if total_antes:
        resumen += "   -> %s bytes menos (%.1f %%)" % (
            format(ahorro, ","), 100.0 * ahorro / total_antes)
    print(resumen)
    if problemas:
        print("\nATENCION: %d proyecto(s) con aviso o error. Nada se ha perdido:"
              % problemas)
        print("la copia de archivo de cada uno esta en su carpeta como %s" % ARCHIVO)
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(main())
