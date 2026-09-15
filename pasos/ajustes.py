"""Los AJUSTES del estudio: lo poco que se decide UNA vez y vale para todos.

QUE ES UN AJUSTE Y QUE NO
-------------------------
Un ajuste es una decision que no pertenece a ningun video en concreto: la
calidad con la que se piden las imagenes es la misma manana que hoy, y
preguntarla en cada video seria preguntar quince veces lo mismo. Lo que SI
pertenece a un video --su estilo, su voz, su duracion-- vive en sus params o en
su preset, y no aqui.

Y SOLO ES UN VALOR POR DEFECTO. Cambiar un ajuste NO toca ningun video ya
hecho, a proposito: `calidad` entra en la firma de cada imagen
(`p6_assets`, `firma = medios.huella({... "calidad": p["calidad"] ...})`), asi
que un defecto que se leyera al EJECUTAR dejaria obsoletas de golpe las
imagenes de todos los proyectos que nunca lo fijaron -- y regenerarlas cuesta
dinero de verdad. Por eso el valor se escribe en los params del proyecto CUANDO
SE CREA (ver `crear_proyecto` en app.py) y ahi se queda: lo viejo sigue con lo
que tenia y el modo editor lo puede cambiar video a video como siempre.

LO QUE CUESTA UNA IMAGEN, DE VERDAD
-----------------------------------
La tabla de precios de OpenAI habla de la imagen DEVUELTA, y con eso solo se
entiende la mitad de la factura: a cada plano se le adjuntan las referencias de
estilo, las de reparto y las de continuidad, y ESO se paga como tokens de
entrada. Medido sobre las 1.439 imagenes del historico (`coste_global.jsonl`),
la entrada es la mediana de abajo y sale casi tan cara como la imagen en `low`.

La consecuencia es la que importa al elegir: subir de `low` a `medium` parece
multiplicar por 6,8 y multiplica por 1,7, porque la parte que se multiplica es
la pequena. Sin esta cuenta delante, la pantalla asustaria con un numero falso.
"""
import os

try:
    from nucleo import coste as COSTE
except ImportError:                                   # corriendo desde pasos/
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import coste as COSTE
from nucleo.proyecto import escribir_json, leer_json

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Redirigible igual que el resto: en el servidor cada cuenta tiene el suyo.
RUTA = os.environ.get("ESTUDIO_AJUSTES") or os.path.join(RAIZ_ESTUDIO,
                                                         "ajustes.json")

#: Las calidades que acepta el motor de imagen, de mas barata a mas cara.
CALIDADES = ("low", "medium", "high")

#: El tamano con el que se generan los planos, y por tanto con el que hay que
#: mirar la tabla de precios. Es el de `p6_assets` para 16:9.
TAMANO = "1536x1024"

#: TOKENS DE ENTRADA POR IMAGEN. La MEDIANA de las 1.439 imagenes del historico
#: --p10 3.287, p90 6.741--, no una estimacion. Se usa la mediana y no el p90
#: porque esto es lo que cuesta una imagen tipica; el p90 ensenaria de mas casi
#: siempre. Si cambia cuantas referencias se adjuntan, este numero se vuelve a
#: medir: sale de `coste_global.jsonl`, campo tokens.entrada de las operaciones
#: 'imagen'.
TOKENS_ENTRADA_POR_IMAGEN = 5114

POR_DEFECTO = {
    "calidad_imagen": "low",
    # Si ya se ha pasado por la guia de inicio (las tarjetas que piden las
    # claves al entrar por primera vez). Vive aqui y no en el navegador
    # porque es de la instalacion, no de la pantalla: desde el movil no hay
    # que volver a verla.
    "onboarding_visto": False,
}


def leer():
    """Los ajustes guardados, con los que faltan puestos por defecto."""
    guardado = leer_json(RUTA, {}) or {}
    salida = dict(POR_DEFECTO)
    for clave, valor in guardado.items():
        if clave in POR_DEFECTO:
            salida[clave] = valor
    if salida.get("calidad_imagen") not in CALIDADES:
        salida["calidad_imagen"] = POR_DEFECTO["calidad_imagen"]
    salida["onboarding_visto"] = bool(salida.get("onboarding_visto"))
    return salida


def guardar(cambios):
    """Mezcla `cambios` sobre lo que hay y devuelve los ajustes resultantes.

    Se valida aqui y no en la pantalla: un ajuste con un valor que el motor no
    entiende no da error al guardarlo, lo da meses despues al generar.
    """
    if not isinstance(cambios, dict):
        raise ValueError("los ajustes se cambian con un objeto")
    actual = leer()
    for clave, valor in cambios.items():
        if clave not in POR_DEFECTO:
            raise ValueError(f"ajuste desconocido: {clave!r}")
        if clave == "calidad_imagen" and valor not in CALIDADES:
            raise ValueError(
                f"calidad {valor!r}: solo {', '.join(CALIDADES)}")
        if clave == "onboarding_visto" and not isinstance(valor, bool):
            raise ValueError("onboarding_visto es verdadero o falso")
        actual[clave] = valor
    escribir_json(RUTA, actual)
    return actual


def calidad_imagen():
    """La calidad con la que arranca un proyecto nuevo."""
    return leer()["calidad_imagen"]


def coste_por_imagen(calidad, tamano=TAMANO):
    """Lo que cuesta UNA imagen a esa calidad: la devuelta MAS lo adjuntado.

    Devuelve las dos mitades por separado porque el reparto es justo lo que hay
    que ensenar: sin el, la comparacion entre calidades es de la parte pequena.
    """
    tokens = COSTE.tarifa_tokens() or {}
    por_token_entrada = float(tokens.get("entrada_imagen") or 0.0)
    entrada = TOKENS_ENTRADA_POR_IMAGEN * por_token_entrada
    devuelta = float(COSTE.tarifa_imagen(tamano, calidad) or 0.0)
    return {
        "calidad": calidad,
        "usd_imagen": round(devuelta, 4),
        "usd_referencias": round(entrada, 4),
        "usd_total": round(devuelta + entrada, 4),
        "tokens_entrada": TOKENS_ENTRADA_POR_IMAGEN,
    }


def tabla_de_costes(tamano=TAMANO):
    """Las tres calidades con su coste real y su multiplicador contra la base.

    `veces_total` es lo que de verdad se multiplica la factura y `veces_imagen`
    lo que parece si solo se mira la tabla de OpenAI. Se sirven LOS DOS: la
    diferencia entre 1,7 y 6,8 es la razon de ser de esta pantalla.
    """
    filas = [coste_por_imagen(c, tamano) for c in CALIDADES]
    base = filas[0]
    for fila in filas:
        fila["veces_total"] = (round(fila["usd_total"] / base["usd_total"], 1)
                               if base["usd_total"] else 0.0)
        fila["veces_imagen"] = (round(fila["usd_imagen"] / base["usd_imagen"], 1)
                                if base["usd_imagen"] else 0.0)
    return filas
