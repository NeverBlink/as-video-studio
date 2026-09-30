"""Verifica que fotos claras pasan y capturas de error no se aceptan."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
import p7_callouts as p


class FirmaPrevia(unittest.TestCase):
    def test_imagen_clara_se_conserva_sin_la_firma(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'previa.png')
            im = Image.new('RGB', (32, 28), (212, 221, 231))
            draw = ImageDraw.Draw(im)
            for i, color in enumerate(p.FIRMA_PREVIA):
                draw.rectangle((i*4, 24, i*4+3, 27), fill=color)
            im.save(path)
            p._comprobar_previa(path, (32, 24))
            with Image.open(path) as result:
                self.assertEqual(result.size, (32, 24))
                self.assertEqual(result.getpixel((5, 5)), (212, 221, 231))

    def test_pagina_de_error_sin_firma_se_rechaza(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'error.png')
            for color in ('white', 'black'):
                Image.new('RGB', (32, 28), color).save(path)
                with self.assertRaisesRegex(RuntimeError, 'no confirma'):
                    p._comprobar_previa(path, (32, 24))


if __name__ == '__main__':
    unittest.main()
