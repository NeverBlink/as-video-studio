"""Pasos del Estudio de Video. Cada modulo expone ejecutar(proyecto, params, avisar)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# claves va la PRIMERA y solo depende de la biblioteca estandar: la lee
# cli_claude para saber con que cuenta hablar, y tiene que poder cargarse
# aunque un motor pesado rompa el resto del paquete.
from . import claves  # noqa: E402,F401
from . import cli_claude, comun, estadisticas  # noqa: E402,F401
# login_cli (entrar con una cuenta del CLI desde la pantalla) va justo
# detras: solo depende de cli_claude, y la pantalla de configuracion lo
# busca por `PASOS_MODULOS.login_cli`.
from . import login_cli  # noqa: E402,F401
# asistente (el chat de la burbuja) solo depende de cli_claude: la pantalla lo
# busca por `PASOS_MODULOS.asistente` y tiene que poder contestar que no hay
# sesion aunque un motor pesado rompa el resto del paquete.
from . import asistente  # noqa: E402,F401
# salud_cli (como respondio cada cuenta la ultima vez) solo usa la biblioteca
# estandar; lo lee la pantalla de claves y lo escribe cli_claude en cada llamada.
from . import salud_cli  # noqa: E402,F401
# comprobar_claves (cada clave contra su servicio) y mcp_estudio (las
# herramientas del asistente) van detras: solo dependen de lo de arriba.
from . import comprobar_claves, mcp_estudio  # noqa: E402,F401
# tipografia va antes que nadie: la usan cartelas y p7, y no depende de nada
from . import tipografia  # noqa: E402,F401
# los subtitulos los pinta el navegador en el previsualizador, asi que sus
# trozos con tiempos tienen que salir por la API
from . import subtitulos  # noqa: E402,F401
from . import cartelas, sonido, transiciones  # noqa: E402,F401
# direccion (que se ve en cada plano) solo depende del CLI y del guion:
# corre antes de que exista ninguna imagen, que es lo que la abarata
from . import direccion  # noqa: E402,F401
# redactor: lo mismo un escalon mas arriba -- escribe el prompt ENTERO del plano
# en vez de una linea que el codigo encaja entre modulos. Va detras de direccion
# porque reutiliza su 'dirigible'
from . import redactor  # noqa: E402,F401
from . import catalogo_visual, estilo  # noqa: E402,F401
# cadencia (tiempo <-> palabras) y fuentes (de donde sale el material) los usan
# p2, p3 y app.py. Van DECLARADOS y no colandose de rebote como atributo del
# paquete cuando p3_guion los importa: `PASOS_MODULOS.fuentes` es una promesa,
# y una promesa que se cumple por un efecto lateral se rompe el dia que alguien
# reordene los imports de p3.
from . import cadencia, fuentes  # noqa: E402,F401
# cta (las llamadas a la accion del video: cuantas, donde y a que producto) solo
# depende de la biblioteca estandar. Va DECLARADO por lo mismo que fuentes: lo
# usan p3_guion y app.py, y `PASOS_MODULOS.cta` no puede depender de que p3 lo
# importe primero.
from . import cta  # noqa: E402,F401
from . import conservar, voz_descrita  # noqa: E402,F401
from . import marcas_tts  # noqa: E402,F401
from . import p1_ingesta, p2_brief, p3_guion  # noqa: E402,F401
from . import p4_voz, p5_revision_audio, presets_voz  # noqa: E402,F401
from . import presets_canal, recetas, tono  # noqa: E402,F401
from . import medios, moodboard  # noqa: E402,F401
# encuadres (que clase de plano es cada uno) lo
# Wikimedia Commons; antes se llamaba commons.py, a un typo de comun.py) los
from . import encuadres  # noqa: E402,F401
from . import p6_assets, p7_callouts, p8_render  # noqa: E402,F401
# y repaso (lo que se escribe MIRANDO el video montado) el ultimo de los que
# deciden: reparte notas en cambios de todos los pasos anteriores
from . import repaso  # noqa: E402,F401
# presets_light va el ULTIMO: la muestra de un preset se compone con p7 y
# con cartelas, asi que necesita el paquete entero levantado.
# enrutar_estilo (que hay que rehacer cuando se corrige el estilo con una
# frase) necesita p7_callouts para su vocabulario de valores, asi que va
# detras de el.
from . import enrutar_estilo  # noqa: E402,F401
from . import presets_light  # noqa: E402,F401

MODULOS = {
    "ingesta": p1_ingesta,
    "brief": p2_brief,
    "guion": p3_guion,
    "voz": p4_voz,
    "revision_audio": p5_revision_audio,
    "assets": p6_assets,
    "callouts": p7_callouts,
    "render": p8_render,
}


def modulo_de(paso_id):
    """Modulo que implementa un paso, o None si todavia no esta escrito."""
    return MODULOS.get(str(paso_id))


__all__ = ["catalogo_visual", "conservar", "repaso",
           "cartelas", "claves", "cli_claude", "comun", "direccion",
           "enrutar_estilo", "redactor",
           "login_cli", "asistente", "salud_cli", "comprobar_claves", "mcp_estudio",
           "encuadres", "estadisticas", "estilo",
           "cadencia", "fuentes",
           "marcas_tts", "medios", "moodboard",
           "p1_ingesta", "p2_brief", "p3_guion",
           "p4_voz", "p5_revision_audio", "presets_voz", "presets_canal",
           "presets_light", "recetas", "sonido", "tipografia", "subtitulos", "tono", "transiciones",
           "voz_descrita",
           "p6_assets", "p7_callouts", "p8_render",
           "MODULOS", "modulo_de"]
