"""
Pruebas de cta: la presentacion y las dos llamadas a la accion del video.

Lo que se protege aqui no es que el prompt diga una frase u otra --eso se
reescribe-- sino las cuatro cosas que cuestan dinero o confianza si se rompen:

  1. un canal SIN personaje puede pedir cosas igual (por eso esto es del video);
  2. las casillas viejas del personaje ya no deciden nada: la pantalla lee lo
     guardado, asi que deducirlas dejaria el video haciendo una cosa y la
     pantalla diciendo otra;
  3. lo escrito es una INDICACION y no un texto final: el prompt lo llama
     despues de haber pagado la llamada al CLI;
     patron, no plantilla, para que no salga la misma frase en cada video.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cta  # noqa: E402
import p3_guion  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado,
              f"esperaba {esperado!r}, salio {obtenido!r}")


print("\n== lo que lleva un video que no ha tocado nada: NADA ==")
vacio = cta.normalizar(None)
igual("los tres momentos, y solo esos", sorted(vacio), sorted(cta.MOMENTOS))
comprobar("los TRES vienen apagados: no se presenta ni pide nada",
          all(vacio[m]["puesto"] is False for m in cta.MOMENTOS))
igual("asi que no hay ningun momento activo", cta.activos(vacio), [])
igual("y el prompt no dice nada", cta.bloque_para_guion(vacio), "")
igual("y ninguno trae texto",
      sorted({vacio[m]["texto"] for m in cta.MOMENTOS}), [""])

#: las tres marcadas: es lo que hay que decir a mano para probar el resto
base = cta.normalizar({m: {"puesto": True} for m in cta.MOMENTOS})

print("\n== las tres casillas son independientes ==")
solo_medio = cta.normalizar({"presentacion": {"puesto": False},
                             "cta_medio": {"puesto": True},
                             "cta_final": {"puesto": False}})
igual("se puede querer solo la de mitad",
      [m for m, _ in cta.activos(solo_medio)], ["cta_medio"])
ninguno = cta.normalizar({m: {"puesto": False} for m in cta.MOMENTOS})
igual("se pueden quitar las tres", cta.activos(ninguno), [])
igual("y entonces el prompt no dice nada", cta.bloque_para_guion(ninguno), "")
comprobar("lo escrito no se borra al desmarcar: se guarda por si vuelve",
          cta.normalizar({"cta_final": {"puesto": False,
                                        "texto": "que se suscriba"}}
                         )["cta_final"]["texto"] == "que se suscriba")

print("\n== esto es del VIDEO y de nadie mas ==")
#: NO HAY PERSONAJES QUE DEN LA CARA. Las llamadas las dice la voz en off,
#: que es la unica que hay, asi que el prompt no habla de quien las dice:
#: nombrar a alguien que no existe es como se acaba con un bloque marcado
#: para nadie.
suyo = cta.bloque_para_guion(base)
comprobar("un video pide igual sin que nadie de la cara", bool(suyo))
comprobar("y el prompt no habla de quien las dice",
          "QUIEN LOS DICE" not in suyo)
comprobar("ni marca bloques de personaje", '"personaje": true' not in suyo)

print("\n== un proyecto de antes del 06-09-2026 ==")
#: LO VIEJO YA NO DECIDE NADA, y esa es la comprobacion. Las casillas del
#: personaje (`presentarse`/`cta`) se aceptan al leer un preset guardado
#: entonces, pero no encienden ningun momento: la pantalla lee lo GUARDADO y no
#: sabe deducirlas, asi que traducirlas dejaria el video haciendo una cosa y la
#: pantalla diciendo otra.
igual("las casillas viejas del personaje ya no encienden nada",
      cta.activos(cta._normalizar({"personajes": [
          {"nombre": "Adrian", "presentarse": True, "cta": True}]},
          estricto=False)["cta"]), [])
igual("sin personajes y sin nada guardado, los defectos",
      cta._normalizar({}, estricto=False)["cta"], cta.POR_DEFECTO)
comprobar("y lo guardado se respeta tal cual",
          cta._normalizar({"cta": {"presentacion": {"puesto": True}}},
                          estricto=False)["cta"]["presentacion"]["puesto"] is True)

print("\n== el bloque del prompt ==")
texto = cta.bloque_para_guion(base)
comprobar("nombra la presentacion como uno de los momentos",
          "· LA PRESENTACION --" in texto)
comprobar("y las dos llamadas",
          "DE MITAD" in texto and "DEL CIERRE" in texto)
#: NADA DE CATALOGOS NI DE MARCAS. Lo unico que entra en el prompt es lo
#: que se ha escrito: sin desplegables de producto no hay un nombre que
#: pueda colarse porque nadie se acordo de apagarlo.
comprobar("dice como se escriben, que es una frase y no un anuncio",
          "COMO SE ESCRIBEN" in texto)
comprobar("y prohibe las coletillas",
          "campanita" in texto)
pedido = cta.bloque_para_guion(cta.normalizar(
    {"cta_medio": {"puesto": True, "texto": "que entre en mi web"}}))
comprobar("dice lo que se ha pedido, con esas palabras",
          "que entre en mi web" in pedido)
#: LA DEL FINAL ES EL ULTIMO BLOQUE, y punto. Hubo un cierre de marca que le
#: ganaba el sitio --la firma de un producto-- y se fue con el producto: ya
#: no hay nada detras de la narracion con lo que pelearse.
comprobar("la del final es el ultimo bloque",
          "EN EL ULTIMO BLOQUE" in cta.bloque_para_guion(base))
#: LAS DOS QUE SALIERON DE REPASAR UN VIDEO LARGO (28-09-2026): la
#: presentacion saltaba a un tema que el video no habia tocado, y lo que se
#: recomendaba iba sin decir de que trataba. Las dos se arreglaron a mano.
comprobar("pide tender el puente antes de hablar de un tema nuevo",
          "EL PUENTE VA PRIMERO" in texto)
comprobar("y decir en una frase que se lleva quien le haga caso",
          "QUE SE LLEVA QUIEN LE HAGA CASO" in texto)
#: SIN FICHA DE PRODUCTO, lo que se lleva sale de la indicacion y de nada mas:
#: sacarlo de otro sitio seria prometer en el video algo que nadie ha escrito.
comprobar("que sale SOLO de la indicacion, sin inventar nada",
          "UNICAMENTE de lo que diga la indicacion" in texto
          and "no se inventa nada" in texto)
comprobar("y lo que la indicacion diga expresamente sigue mandando",
          "expresamente" in texto and "manda sobre esta regla" in texto)
comprobar("con una sola presentacion el puente tambien se pide: es donde mas falta",
          "EL PUENTE VA PRIMERO" in cta.bloque_para_guion(
              cta.normalizar({"presentacion": {"puesto": True}})))

print("\n== el texto es una indicacion al redactor: tope de 1.500 ==")
#: Aqui hubo 600 («es una frase, no un guion») y rechazaba las indicaciones con
#: contexto, que son las que salen organicas. Se sube a 1.500, no se quita.
igual("el tope son 1.500 caracteres", cta.MAX_TEXTO, 1500)
indicacion = ("que entre en mi web, donde explico paso a paso como montar esto "
              "en casa sin gastar de mas. ") * 12
comprobar("una indicacion con contexto que con 600 se rechazaba",
          600 < len(indicacion.strip()) <= cta.MAX_TEXTO,
          f"mide {len(indicacion.strip())}")
igual("se guarda entera",
      cta.normalizar({"cta_medio": {"texto": indicacion}})["cta_medio"]["texto"],
      indicacion.strip())
try:
    cta.normalizar({"cta_medio": {"texto": "x" * (cta.MAX_TEXTO + 1)}})
    comprobar("un texto pasado de largo se rechaza", False,
              "no ha levantado ValueError")
except ValueError as fallo:
    comprobar("un texto pasado de largo se rechaza", True)
    comprobar("y el mensaje dice que es una indicacion, no el guion del bloque",
              "indicacion" in str(fallo) and str(cta.MAX_TEXTO) in str(fallo),
              str(fallo))
igual("sin estricto se corta en vez de reventar",
      len(cta.normalizar({"cta_medio": {"texto": "x" * (cta.MAX_TEXTO + 50)}},
                         estricto=False)["cta_medio"]["texto"]), cta.MAX_TEXTO)

print("\n== dentro de los params del guion ==")
opciones = p3_guion._normalizar({}, estricto=False)
igual("un proyecto sin `cta` no pide nada",
      cta.activos(opciones["cta"]), [])
elegidas = p3_guion._normalizar(
    {"cta": {"cta_medio": {"puesto": True,
                           "texto": "que entre en mi web"}}},
    estricto=False)
igual("lo que se pide llega hasta el paso",
      elegidas["cta"]["cta_medio"]["texto"], "que entre en mi web")
#: EL TOPE ES DEL MOTOR Y NO DE LA PANTALLA: un limite que solo vive en la
#: interfaz se salta con una llamada a la API, y lo que hay detras son
#: tokens que se pagan en cada video.
try:
    p3_guion._normalizar(
        {"cta": {"cta_medio": {"texto": "x" * (cta.MAX_TEXTO + 1)}}},
        estricto=True)
    comprobar("el paso rechaza un texto pasado de largo", False,
              "no ha levantado ValueError")
except ValueError:
    comprobar("el paso rechaza un texto pasado de largo", True)
igual("y deja pasar entera la indicacion larga que antes rechazaba",
      p3_guion._normalizar({"cta": {"cta_medio": {"puesto": True,
                                                  "texto": indicacion}}},
                           estricto=True)["cta"]["cta_medio"]["texto"],
      indicacion.strip())

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CTA OK: todo en orden")
