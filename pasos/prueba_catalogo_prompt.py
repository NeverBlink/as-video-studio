"""El catalogo puede preparar el prompt sin los personajes fijos retirados."""
import unittest
from unittest.mock import patch
import catalogo_visual as catalogo


class PromptCatalogo(unittest.TestCase):
    def test_guion_llega_al_modelo_sin_personajes_fijos(self):
        class PromptRecibido(Exception):
            pass

        def recibir(prompt, *args):
            self.assertIn('Revisa el contrato de la vivienda.', prompt)
            self.assertIn('Fotografia sobria', prompt)
            self.assertIn('Compra sobre plano', prompt)
            raise PromptRecibido()

        with patch.object(catalogo, '_llamar_claude', side_effect=recibir) as llamada, \
                patch.object(catalogo.estadisticas, 'anotar'):
            with self.assertRaises(PromptRecibido):
                catalogo.proponer(
                    [{'id': 'B001', 'texto': 'Revisa el contrato de la vivienda.'}],
                    brief={'titulo': 'Compra sobre plano'},
                    peticion='Fotografia sobria')
            llamada.assert_called_once()


if __name__ == '__main__':
    unittest.main()
