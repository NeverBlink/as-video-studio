"""
Pruebas de marcas_tts: las anotaciones de voz que van dentro del guion.

Lo que se protege aqui es, casi todo, cosas que se midieron contra la API de
Cartesia y que no estan en su documentacion. Ver la cabecera de marcas_tts.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import marcas_tts as m  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado, f"esperaba {esperado!r}, salio {obtenido!r}")


print("\n== limpiar: el texto tal y como se oye ==")
igual("quita un break",
      m.limpiar('La víctima era Aurora.<break time="900ms"/>Mayo de 2024.'),
      "La víctima era Aurora. Mayo de 2024.")
igual("quita speed y volume",
      m.limpiar('<speed ratio="0.9"/>Uno dos.<volume ratio="1"/> Tres.'),
      "Uno dos. Tres.")
igual("conserva el contenido de spell",
      m.limpiar('El protocolo <spell>MFA</spell> no estaba puesto.'),
      "El protocolo MFA no estaba puesto.")
igual("quita tambien lo que no es del vocabulario",
      m.limpiar("Hola. <pausa larga/> Adiós."), "Hola. Adiós.")
igual("texto sin marcas se queda igual",
      m.limpiar("Treinta millones de clientes."), "Treinta millones de clientes.")
igual("no pega dos palabras al quitar la etiqueta en medio",
      m.limpiar('uno<break time="300ms"/>dos'), "uno dos")

print("\n== contar_palabras: la horquilla se mide sobre lo que se oye ==")
igual("no cuenta las etiquetas",
      m.contar_palabras('Cuatro palabras de verdad.<break time="900ms"/>'), 4)
igual("cuenta lo que se deletrea",
      m.contar_palabras('El <spell>MFA</spell> faltaba.'), 3)

print("\n== sanear: lo que se manda a Cartesia ==")
igual("una etiqueta valida sobrevive intacta",
      m.sanear('Uno.<break time="900ms"/>Dos.'), 'Uno.<break time="900ms"/>Dos.')
igual("segundos con decimal pasan a milisegundos",
      m.sanear('Uno.<break time="0.8s"/>Dos.'), 'Uno.<break time="800ms"/>Dos.')

# Leccion 2: lo que Cartesia no reconoce, LO LOCUTA. Medido: <pausa larga/>
# volvio en las marcas de palabra como "<pausa" y "larga/>".
igual("una etiqueta inventada se BORRA, no se avisa y se deja",
      m.sanear("Hola. <pausa larga/> Adiós."), "Hola.  Adiós.")
comprobar("y ademas lo cuenta como problema",
          any("vocabulario" in p for p in m.revisar("Hola. <pausa larga/> Adiós.")))
igual("una emocion que no existe se borra",
      m.sanear('<emotion value="inventada"/>Hola.'), "Hola.")

# Leccion 4: speed y volume persisten HASTA EL FINAL DEL TRANSCRIPT.
print("\n== cada bloque se cierra solo (lo mas importante) ==")
igual("un speed sin cerrar se cierra al final del bloque",
      m.sanear('<speed ratio="0.9"/>Frase lenta.'),
      '<speed ratio="0.9"/>Frase lenta.<speed ratio="1"/>')
igual("un volume sin cerrar tambien",
      m.sanear('<volume ratio="0.8"/>Bajito.'),
      '<volume ratio="0.8"/>Bajito.<volume ratio="1"/>')
igual("si el redactor ya lo cerro, no se cierra dos veces",
      m.sanear('<speed ratio="0.9"/>Lenta.<speed ratio="1"/>'),
      '<speed ratio="0.9"/>Lenta.<speed ratio="1"/>')
comprobar("y se avisa de que hubo que cerrarlo",
          any("hasta el final del video" in p
              for p in m.revisar('<speed ratio="0.9"/>Frase lenta.')))
igual("los dos abiertos se cierran los dos",
      m.sanear('<speed ratio="0.9"/><volume ratio="0.8"/>Hola.'),
      '<speed ratio="0.9"/><volume ratio="0.8"/>Hola.<speed ratio="1"/><volume ratio="1"/>')

print("\n== rangos ==")
igual("speed por encima del maximo de Cartesia se acota",
      m.sanear('<speed ratio="3"/>Hola.<speed ratio="1"/>'),
      '<speed ratio="1.5"/>Hola.<speed ratio="1"/>')
igual("volume por debajo del minimo se acota",
      m.sanear('<volume ratio="0.1"/>Hola.<volume ratio="1"/>'),
      '<volume ratio="0.5"/>Hola.<volume ratio="1"/>')
igual("un silencio ridiculo se quita",
      m.sanear('Uno.<break time="20ms"/>Dos.'), "Uno.Dos.")
igual("un silencio absurdo se recorta al techo",
      m.sanear('Uno.<break time="9000ms"/>Dos.'),
      f'Uno.<break time="{m.BREAK_MAX_MS}ms"/>Dos.')

print("\n== colocacion: los cambios de voz no parten una frase ==")
igual("speed a mitad de frase se quita",
      m.sanear('La víctima <speed ratio="0.9"/>era Aurora.'),
      "La víctima era Aurora.")
igual("speed detras de un punto se queda",
      m.sanear('Uno. <speed ratio="0.9"/>Dos.<speed ratio="1"/>'),
      'Uno. <speed ratio="0.9"/>Dos.<speed ratio="1"/>')
igual("emocion al empezar el bloque se queda",
      m.sanear('<emotion value="sad"/>Nadie volvió.'),
      '<emotion value="sad"/>Nadie volvió.')
igual("emocion a mitad de frase se quita",
      m.sanear('Nadie <emotion value="sad"/>volvió.'), "Nadie volvió.")
igual("break a mitad de frase SI se queda: es el recurso de suspense",
      m.sanear('La víctima era,<break time="300ms"/> Aurora.'),
      'La víctima era,<break time="300ms"/> Aurora.')
igual("detras de puntos suspensivos tambien es frontera",
      m.sanear('Y entonces... <speed ratio="0.9"/>nada.<speed ratio="1"/>'),
      'Y entonces... <speed ratio="0.9"/>nada.<speed ratio="1"/>')

print("\n== silencios encadenados (Cartesia avisa de alucinacion) ==")
igual("dos breaks seguidos se funden en uno",
      m.sanear('Uno.<break time="600ms"/><break time="600ms"/>Dos.'),
      'Uno.<break time="1200ms"/>Dos.')
igual("fundidos, tampoco pasan del techo",
      m.sanear('Uno.<break time="2000ms"/><break time="2000ms"/>Dos.'),
      f'Uno.<break time="{m.BREAK_MAX_MS}ms"/>Dos.')

print("\n== el silencio del final del bloque se conserva ==")
# Es el caso que motivo todo esto: el gancho (B001) y la entrada del documental
# (B002) salian pegados. La pausa va al final de B001 y tiene que sobrevivir.
igual("un break al final del bloque se queda",
      m.sanear('La víctima era Aurora.<break time="900ms"/>'),
      'La víctima era Aurora.<break time="900ms"/>')
igual("y se cierra el bloque despues del silencio, no antes",
      m.sanear('<speed ratio="0.9"/>Lenta.<break time="900ms"/>'),
      '<speed ratio="0.9"/>Lenta.<break time="900ms"/><speed ratio="1"/>')

print("\n== la pausa del gancho no se deja a criterio de nadie ==")
igual("si no hay ninguna, se pone",
      m.pausa_al_final("El gancho remata aquí.", 900),
      'El gancho remata aquí.<break time="900ms"/>')
igual("si ya hay una mas larga, no se toca",
      m.pausa_al_final('El gancho.<break time="1200ms"/>', 900),
      'El gancho.<break time="1200ms"/>')
igual("si la hay pero corta, se SUSTITUYE (no se encadenan dos)",
      m.pausa_al_final('El gancho.<break time="250ms"/>', 900),
      'El gancho.<break time="900ms"/>')
igual("el cierre del bloque sigue detras de la pausa",
      m.pausa_al_final('<speed ratio="0.9"/>El gancho.', 900),
      '<speed ratio="0.9"/>El gancho.<break time="900ms"/><speed ratio="1"/>')
igual("con 0 no hace nada", m.pausa_al_final("El gancho.", 0), "El gancho.")
igual("un bloque sin texto no se inventa una pausa",
      m.pausa_al_final("", 900), "")
for muestra in ("El gancho.", 'El gancho.<break time="250ms"/>',
                '<speed ratio="0.9"/>El gancho.'):
    puesta = m.pausa_al_final(muestra, 900)
    comprobar(f"no cambia lo que se oye: {muestra[:30]}...",
              m.limpiar(puesta) == m.limpiar(muestra))
    comprobar(f"idempotente: {muestra[:30]}...",
              m.pausa_al_final(puesta, 900) == puesta)
    comprobar(f"garantia cumplida: {muestra[:30]}...",
              m.silencio_final(puesta) >= 900)

print("\n== <spell> solo deletrea siglas, no frases ==")
# Medido con whisperx sobre la toma real: «<spell>AT and T</spell>» se oyó
# «AT, A-N-D-T» -- deletreaba la palabra 'and'. Y de paso rompía el karaoke: en
# el texto son tres tokens y en las marcas uno.
igual("una sigla suelta se queda como está",
      m.sanear('Sin <spell>MFA</spell> puesto.'), 'Sin <spell>MFA</spell> puesto.')
igual("varias palabras dentro se parten, y solo se deletrea la sigla",
      m.sanear('El banco <spell>AT and T</spell> cayó.'),
      'El banco <spell>AT</spell> and <spell>T</spell> cayó.')
igual("una letra suelta sí es sigla",
      m.sanear('<spell>T</spell> mayúscula.'), '<spell>T</spell> mayúscula.')
igual("una palabra corriente no se deletrea aunque sea corta",
      m.sanear('Ni <spell>una palabra larga</spell> aquí.'),
      'Ni una palabra larga aquí.')
comprobar("y se avisa de lo que se ha sacado del spell",
          any("no se deletrea" in p
              for p in m.revisar('El banco <spell>AT and T</spell> cayó.')))

# EL GATE: se deletrea lo que NO se puede pronunciar, y lo decide el MOTOR.
# Nacio de un video real donde de seis nombres de malware tres salieron
# deletreados letra a letra y tres leidos, sin patron: «va en mayusculas» se
# parece demasiado a «es una sigla».
print(chr(10) + "== que se deletrea de verdad: lo manda el motor, no el redactor ==")
for token in ("MFA", "FBI", "CIA", "API", "UNC", "IP", "DNS", "SQL", "GCHQ",
              "NCSC", "HTML", "USB", "CEO", "ATM", "2FA"):
    comprobar(f"{token} se deletrea", m.es_inicialismo(token))
for token in ("NASA", "OTAN", "MEGA", "CISA", "NATO", "LUMMA", "VIDAR",
              "SWIFT", "STEALC", "RACCOON", "REDLINE", "ALEXHOST",
              "SMOKELOADER", "SIM", "PIN", "RAM", "LAN"):
    comprobar(f"{token} se LEE: se puede pronunciar", not m.es_inicialismo(token))
for token in ("AlexHost", "Mega", "stealer", "Lumma"):
    comprobar(f"{token} no va en mayusculas, asi que no es sigla",
              not m.es_inicialismo(token))
igual("y el gate se aplica pase lo que pase en el prompt",
      m.sanear('Usaron <spell>LUMMA</spell> y <spell>MFA</spell>.'),
      'Usaron LUMMA y <spell>MFA</spell>.')
for muestra in ('El banco <spell>AT and T</spell> cayó.',
                'Sin <spell>MFA</spell> puesto.'):
    puesto = m.sanear(muestra)
    comprobar(f"no cambia lo que se oye: {muestra[:32]}...",
              m.limpiar(puesto) == m.limpiar(muestra))
    comprobar(f"idempotente: {muestra[:32]}...", m.sanear(puesto) == puesto)

print("\n== densidad: la toma tiene que seguir sonando continua ==")
pocos = [{"texto": 'Uno.<break time="900ms"/>'}] + [{"texto": "Dos."}] * 5
comprobar("un silencio en seis bloques no molesta", not m.revisar_conjunto(pocos))
muchos = [{"texto": f'Bloque.<break time="900ms"/>'} for _ in range(6)]
comprobar("un silencio en cada bloque si avisa",
          any("continua" in p for p in m.revisar_conjunto(muchos)))
comprobar("guion vacio no revienta", m.revisar_conjunto([]) == [])

print("\n== idempotencia: sanear dos veces da lo mismo ==")
for muestra in ('<speed ratio="0.9"/>Lenta.',
                'Uno.<break time="600ms"/><break time="600ms"/>Dos.',
                'Hola. <pausa larga/> Adiós.',
                'La víctima <speed ratio="0.9"/>era Aurora.',
                '<emotion value="sad"/>Nadie volvió.<break time="900ms"/>'):
    una = m.sanear(muestra)
    comprobar(f"idempotente: {muestra[:38]}...", m.sanear(una) == una,
              f"{una!r} -> {m.sanear(una)!r}")

print("\n== el texto limpio no cambia al sanear ==")
for muestra in ('Uno.<break time="600ms"/>Dos.',
                '<speed ratio="0.9"/>Lenta.',
                'El <spell>MFA</spell> faltaba.'):
    comprobar(f"sanear no toca lo que se oye: {muestra[:34]}...",
              m.limpiar(m.sanear(muestra)) == m.limpiar(muestra),
              f"{m.limpiar(muestra)!r} -> {m.limpiar(m.sanear(muestra))!r}")

print("\n== las marcas que devuelve Cartesia ==")
igual("una palabra normal pasa tal cual", m.texto_de_marca("Aurora."), "Aurora.")
# Medido en los dos idiomas: <spell> es la UNICA etiqueta que Cartesia devuelve
# DENTRO de word_timestamps. Con «Uno <spell>ABC</spell> dos.» vuelven
# ['Uno', '<spell>ABC</spell>', 'dos.'].
igual("de <spell>ABC</spell> se saca la palabra, NO se tira",
      m.texto_de_marca("<spell>ABC</spell>"), "ABC")
igual("con la puntuacion que lleve pegada",
      m.texto_de_marca("<spell>ABC</spell>,"), "ABC,")
comprobar("cualquier otra cosa con angulos si se tira",
          m.texto_de_marca("<pausa") is None and m.texto_de_marca("larga/>") is None)
comprobar("NO se come palabras inglesas corrientes",
          not any(m.es_token_de_etiqueta(p)
                  for p in ("break", "speed", "volume", "time", "spell")))

# La que habria cazado el fallo: contar las marcas de vuelta contra lo que el
# reparto espera. Si <spell> se tirase, saldria una palabra menos y todos los
# cortes de plano del resto del bloque irian corridos.
bloque = 'El banco <spell>ING</spell> confirmo el acceso.'
devueltas = ['El', 'banco', '<spell>ING</spell>', 'confirmo', 'el', 'acceso.']
utiles = [x for x in (m.texto_de_marca(w) for w in devueltas) if x is not None]
igual("las marcas cuadran con lo que espera el reparto",
      len(utiles), len(m.limpiar(bloque).split()))

print("\n== casos limite ==")
igual("texto vacio", m.sanear(""), "")
igual("None", m.sanear(None), "")
igual("solo una etiqueta y nada de texto", m.sanear('<break time="900ms"/>'), "")
comprobar("hay_marcas distingue", m.hay_marcas('Uno.<break time="1s"/>')
          and not m.hay_marcas("Uno dos tres."))
igual("resumen cuenta por clase",
      m.resumen([{"texto": 'Uno.<break time="900ms"/>Dos.'},
                 {"texto": '<emotion value="sad"/>Tres.'}])["break"], 1)

print("\n== cifras y simbolos: el guion se locuta, no se lee ==")
# El fallo que trajo esto: un guion en INGLES con «Spain, May 2024» se locuto
# «may dos mil veinticuatro». Una cifra no es una palabra: es algo que hay que
# expandir, y quien la expande no es quien escribio la frase.
import comun  # noqa: E402

for texto, espera, que in (
        ("Spain, May 2024. Aurora confirms.", True, "un año en cifras"),
        ("Spain, May twenty twenty-four. Aurora confirms.", False, "el mismo con letras"),
        ("El 2% de la economía.", True, "un porcentaje"),
        ("El dos por ciento de la economía.", False, "el mismo con letras"),
        ("$2.000.000.", True, "dinero en cifras"),
        ("Dos millones de dólares.", False, "el mismo con letras"),
        ("Microsoft y AT&T.", True, "un ampersand"),
        ("Treinta millones de clientes.", False, "un texto limpio"),
        ("", False, "texto vacío")):
    comprobar(f"detecta {que}: {texto[:38]!r}",
              comun.revisar_cifras(texto)["hay_cifras"] == espera)

# Y lo que NO puede pasar: que las anotaciones de voz cuenten como cifras. Los
# milisegundos de un <break> llevan dígitos y no se locutan.
comprobar("una anotación de voz no cuenta como cifra",
          not comun.revisar_cifras(
              m.limpiar('Se acabó.<break time="900ms"/>'))["hay_cifras"])
comprobar("ni un <speed ratio=\"0.9\"/>",
          not comun.revisar_cifras(
              m.limpiar('<speed ratio="0.9"/>Lento.<speed ratio="1"/>'))["hay_cifras"])
igual("y da ejemplos concretos para poder corregirlo",
      comun.revisar_cifras("May 2024 y el 2%")["ejemplos"], ["2024", "2%"])

print("\n== las instrucciones para el modelo ==")
texto = m.instrucciones()
comprobar("nombran el break", "break" in texto)
comprobar("dicen que hay que cerrar el bloque", 'ratio="1"' in texto)
comprobar("avisan de que las etiquetas van en ingles", "EN INGLES" in texto)
comprobar("se puede quitar la emocion",
          "emotion" not in m.instrucciones(con_emocion=False))

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("todo en orden")
