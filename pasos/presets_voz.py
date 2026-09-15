"""
Presets de estilo de voz para el paso 4.

Un preset fija de golpe los cuatro mandos que de verdad cambian como suena una
narracion: modelo, velocidad, emociones y aire entre bloques. El usuario elige
"true_crime_tenso" y no tiene que saber que eso son controles experimentales de
Cartesia.

Las emociones son las etiquetas que acepta Cartesia y ninguna mas:
    anger | curiosity | positivity | sadness | surprise
con nivel opcional lowest | low | (sin nivel) | high | highest.
Cualquier otra etiqueta la rechaza la API con HTTP 400, asi que aqui solo hay
combinaciones verificadas contra el endpoint real.

Las emociones son ADITIVAS: no restan. Por eso un tono neutro se consigue con la
lista vacia, no con "sadness:lowest".

Las voces sugeridas son voces publicas en espanol del catalogo de Cartesia,
comprobadas contra /voices. La primera de la lista es la recomendada.
"""
import copy

# ids reales del catalogo publico de Cartesia (idioma es)
VOZ_LUIS = "b5aa8098-49ef-475d-89b0-c9262ecf33fd"        # Luis - News Caster
VOZ_HECTOR = "b042270c-d46f-4d4f-8fb0-7dd7c5fe5615"      # Hector - Tour Leader
VOZ_MARCOS = "13ff5deb-2591-42ad-a356-63a04e524411"      # Marcos - Steady Advisor
VOZ_GONZALO = "58e531e3-b212-49df-adee-c335a19c2429"     # Gonzalo - Grounded Storyteller
VOZ_RAFAEL = "cbb6fdf0-30dd-49f6-af7d-bbb1185c1fa5"      # Rafael - Poised Advisor
VOZ_ALONSO = "4853bafa-52cc-48c8-86a1-1edf8c76e429"      # Alonso - Podcast Explainer
VOZ_ISABEL = "c0c374aa-09be-42d9-9828-4d2d7df86962"      # Isabel - Teacher
VOZ_BLANCA = "538a8872-3799-4df5-b373-b78493b766c6"      # Blanca - Graceful Host
VOZ_IRIA = "a7beff01-8f8b-4809-bfe6-e2166e57e0c2"        # Iria - Thoughtful Communicator
VOZ_AGUSTIN = "2695b6b5-5543-4be1-96d9-3967fb5e7fec"     # Agustin - Clear Storyteller
VOZ_MIGUEL = "d813d699-27f0-4231-83b4-6bd1bce106ba"      # Miguel - Route Guide
VOZ_NURIA = "9d8c6b2e-0a23-4a15-ae1b-121d5b5af417"       # Nuria - Trusted Advisor
VOZ_ESTEBAN = "392e340d-bf73-4199-9f46-8baca484f4cb"     # Esteban - Crisp Operator
VOZ_PEDRO = "15d0c2e2-8d29-44c3-be23-d585d5f154a1"       # Pedro - Formal Speaker
VOZ_ANDRES = "d46e87a1-7c6d-4b18-9359-926f4a35ffdf"      # Andres - Trusted Voice
VOZ_LAURA = "1cc00672-e9d4-455e-b3fb-31dfb7aad231"       # Laura - Trustworthy Guide

PRESETS = {
    "documental_sobrio": {
        "nombre": "Documental sobrio",
        "descripcion": (
            "Narrador clasico de documental: neutro, un punto por debajo del "
            "ritmo natural, sin color emocional. Deja que hablen los hechos. "
            "Es el que no se equivoca nunca."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "slow",
        "emociones": [],
        "hueco_minimo": 1.0,
        "voces_sugeridas": [VOZ_LUIS, VOZ_MARCOS, VOZ_HECTOR],
    },
    "true_crime_tenso": {
        "nombre": "True crime tenso",
        "descripcion": (
            "Voz baja y contenida con curiosidad alta y un poso de tristeza: "
            "suena a que lo que viene despues es peor. Huecos largos entre "
            "bloques para que respire la amenaza."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "slow",
        "emociones": ["curiosity:high", "sadness:low"],
        "hueco_minimo": 1.3,
        "voces_sugeridas": [VOZ_GONZALO, VOZ_RAFAEL, VOZ_HECTOR],
    },
    "divulgacion_cercana": {
        "nombre": "Divulgacion cercana",
        "descripcion": (
            "Explicador de canal grande: ritmo normal, energia positiva y "
            "curiosidad. Encadena rapido para que no se caiga la atencion."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "normal",
        "emociones": ["positivity:high", "curiosity"],
        "hueco_minimo": 0.6,
        "voces_sugeridas": [VOZ_ALONSO, VOZ_ISABEL, VOZ_BLANCA],
    },
    "urgente_noticia": {
        "nombre": "Urgente de noticia",
        "descripcion": (
            "Cabecera de informativo: rapido, con sorpresa alta y una pizca de "
            "enfado. Huecos minimos, sensacion de directo. Cansa si dura mas "
            "de un minuto, uselo en aperturas."
        ),
        "modelo": "sonic-3",
        "velocidad": "fast",
        "emociones": ["surprise:high", "anger:low"],
        "hueco_minimo": 0.3,
        "voces_sugeridas": [VOZ_LUIS, VOZ_ESTEBAN, VOZ_NURIA],
    },
    "reflexivo_pausado": {
        "nombre": "Reflexivo pausado",
        "descripcion": (
            "Ensayo en voz alta: lo mas lento del catalogo, curiosidad y "
            "tristeza suaves, silencios largos. Para cierres, epilogos y "
            "planos contemplativos."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "slowest",
        "emociones": ["curiosity:low", "sadness:low"],
        "hueco_minimo": 1.6,
        "voces_sugeridas": [VOZ_IRIA, VOZ_AGUSTIN, VOZ_MIGUEL],
    },
    "testimonio_seco": {
        "nombre": "Testimonio seco",
        "descripcion": (
            "Lectura de acta: velocidad normal, cero emocion anadida, huecos "
            "cortos. Suena a informe, a dato verificado. Contrasta muy bien "
            "intercalado con un preset emocional."
        ),
        "modelo": "sonic-3",
        "velocidad": "normal",
        "emociones": [],
        "hueco_minimo": 0.8,
        "voces_sugeridas": [VOZ_PEDRO, VOZ_MARCOS, VOZ_ANDRES],
    },
    "denuncia_indignada": {
        "nombre": "Denuncia indignada",
        "descripcion": (
            "Periodismo de trinchera: enfado alto con algo de tristeza, ritmo "
            "normal para que se entienda cada acusacion. Para el bloque en el "
            "que el video toma partido."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "normal",
        "emociones": ["anger:high", "sadness:low"],
        "hueco_minimo": 0.7,
        "voces_sugeridas": [VOZ_RAFAEL, VOZ_LUIS, VOZ_LAURA],
    },
    "confidencia_susurrada": {
        "nombre": "Confidencia susurrada",
        "descripcion": (
            "Como si contara algo que no deberia: lento, curiosidad muy alta y "
            "nada de positividad. Bueno para revelaciones y giros a mitad de "
            "video."
        ),
        "modelo": "sonic-3.5",
        "velocidad": "slowest",
        "emociones": ["curiosity:highest"],
        "hueco_minimo": 1.2,
        "voces_sugeridas": [VOZ_GONZALO, VOZ_IRIA, VOZ_HECTOR],
    },
}

POR_DEFECTO = "documental_sobrio"


def listar():
    """Presets disponibles como lista de fichas con su id, para pintar la UI."""
    fichas = []
    for identificador, datos in PRESETS.items():
        ficha = copy.deepcopy(datos)
        ficha["id"] = identificador
        fichas.append(ficha)
    fichas.sort(key=lambda f: f["nombre"])
    return fichas


def preset(identificador):
    """Copia de un preset por id; falla claro si no existe."""
    clave = str(identificador or "").strip()
    if clave not in PRESETS:
        raise ValueError(f"preset de voz desconocido: {identificador!r}. "
                         f"Disponibles: {', '.join(sorted(PRESETS))}")
    return copy.deepcopy(PRESETS[clave])
