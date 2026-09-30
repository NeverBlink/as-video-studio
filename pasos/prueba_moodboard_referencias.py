"""Regresion del estilo descrito: sus imagenes llegan al motor, sin pagar API."""
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moodboard


class ReferenciasDescritas(unittest.TestCase):
    def test_adjunta_las_imagenes_y_conserva_idioma_y_correccion(self):
        with tempfile.TemporaryDirectory() as tmp:
            rutas = []
            for i, color in enumerate(('red', 'green', 'blue')):
                ruta = str(Path(tmp) / f'{i}.png')
                Image.new('RGB', (80, 100), color).save(ruta)
                rutas.append(ruta)
            normalizar = Mock(side_effect=lambda ruta, cache: ruta)
            llamadas = []

            def generar(prompt, referencias, **kwargs):
                self.assertTrue(referencias, 'El motor de edicion exige adjuntos')
                self.assertTrue(all(os.path.isfile(p) for p in referencias))
                with Image.open(referencias[0]) as sheet:
                    self.assertGreater(sheet.width, 0)
                llamadas.append(prompt)
                buf = io.BytesIO()
                Image.new('RGB', (32, 32)).save(buf, format='PNG')
                return buf.getvalue(), {'coste': 0}

            motor = SimpleNamespace(normalizar=normalizar, generar=generar)
            reglas = SimpleNamespace(bloque_prompt=lambda _: '')
            p6 = SimpleNamespace(MAX_CADENAS=1, guia_escrita=lambda _: ['Photographic style.'])
            with patch.dict(sys.modules, {'p6_assets': p6}), patch.object(
                    moodboard.medios, 'motor', side_effect=lambda ruta: motor if ruta.startswith('imagen_') else reglas):
                result = moodboard.dibujar_desde_guia(
                    {'guia': 'Fotografia'}, str(Path(tmp)/'salida'),
                    ejes=['interior'], idioma='es',
                    peticiones={'interior': 'Natural light'}, referencias=rutas)
            self.assertEqual(result['ejes'], ['interior'])
            self.assertTrue(Path(result['rutas'][0]).is_file())
            self.assertEqual([c.args[0] for c in normalizar.call_args_list[:3]], rutas)
            self.assertIn('Natural light', llamadas[0])
            self.assertIn('Spanish', llamadas[0])

    def test_sin_imagenes_falla_antes_de_llamar_al_motor(self):
        motor = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(moodboard.medios, 'motor', return_value=motor):
            with self.assertRaisesRegex(ValueError, 'imagenes aportadas'):
                moodboard.dibujar_desde_guia({'guia': 'Fotografia'}, tmp)
            motor.generar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
