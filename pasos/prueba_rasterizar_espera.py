"""Una captura completa termina aunque Chrome siga vivo; nunca vale la vieja."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import medios


class RasterizarEspera(unittest.TestCase):
    def test_captura_nueva_termina_proceso_vivo(self):
        class Proceso:
            terminado = False
            def __init__(self, orden, **kwargs):
                ruta = next(x.split('=', 1)[1] for x in orden
                            if x.startswith('--screenshot='))
                Image.new('RGB', (32, 24), 'navy').save(ruta)
            def poll(self):
                return 0 if self.terminado else None
            def terminate(self):
                self.terminado = True
            def wait(self, **kwargs):
                return 0
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(medios, 'edge', return_value='chrome'), \
                patch.object(medios.subprocess, 'Popen', Proceso):
            destino = str(Path(tmp) / 'foto.png')
            Image.new('RGB', (32, 24), 'red').save(destino)
            medios.rasterizar('<svg/>', destino, 32, 24)
            with Image.open(destino) as im:
                self.assertEqual(im.getpixel((0, 0)), (0, 0, 128))

    def test_fallo_no_acepta_destino_antiguo(self):
        class Proceso:
            def __init__(self, *args, **kwargs):
                pass
            def poll(self):
                return 1
            def wait(self, **kwargs):
                return 1
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(medios, 'edge', return_value='chrome'), \
                patch.object(medios.subprocess, 'Popen', Proceso), \
                patch.object(medios, 'ESPERA_RASTERIZAR_S', 0):
            destino = Path(tmp) / 'foto.png'
            Image.new('RGB', (32, 24), 'red').save(destino)
            anterior = destino.read_bytes()
            with self.assertRaisesRegex(RuntimeError, 'no genero'):
                medios.rasterizar('<svg/>', str(destino), 32, 24)
            self.assertEqual(destino.read_bytes(), anterior)


if __name__ == '__main__':
    unittest.main()
