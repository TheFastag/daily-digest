# -*- coding: utf-8 -*-
"""
Pruebas unitarias para el módulo summarizer:
- Verificación de formato JSON devuelto por Gemini.
- Verificación de caché por URL.
- Verificación de selección de la Noticia Más Importante del Día en último minuto.
- Verificación de reintentos y fallback a RSS cuando hay error o rate limit.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

import summarizer


class TestSummarizer(unittest.TestCase):

    def setUp(self):
        self.sample_articles = [
            {
                "title": "Avance clave en computación cuántica",
                "link": "https://example.com/quantum-news",
                "raw_summary": "Investigadores han logrado mantener la coherencia cuántica por más de 10 minutos en condiciones normales.",
                "summary": "",
                "summary_source": "pending",
                "is_top_story": False
            },
            {
                "title": "Nuevo satélite meteorológico lanzado con éxito",
                "link": "https://example.com/satellite-launch",
                "raw_summary": "La agencia espacial puso en órbita un nuevo sensor capaz de predecir huracanes con mayor precisión.",
                "summary": "",
                "summary_source": "pending",
                "is_top_story": False
            }
        ]
        self.empty_cache = {}

    def test_rss_fallback(self):
        """Verifica que el fallback recorte y limpie texto correctamente."""
        html_input = "<p>Texto de prueba con <b>etiquetas HTML</b> y espacios   múltiples.</p>"
        result = summarizer.summarize_rss_fallback(html_input, max_chars=50)
        self.assertNotIn("<p>", result)
        self.assertNotIn("<b>", result)
        self.assertTrue(len(result) <= 55)

    def test_cache_hit_skips_gemini(self):
        """Si una URL está en caché, no debe llamar a Gemini."""
        cache = {
            "https://example.com/quantum-news": {
                "summary": "Resumen previamente cacheado con éxito.",
                "source": "ai",
                "timestamp": "2026-10-24T00:00:00Z"
            }
        }
        with patch("summarizer.get_gemini_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch("summarizer.call_gemini_batch") as mock_call:
                mock_call.return_value = {
                    "resumenes": [{"id": "1", "resumen": "Resumen para el satélite."}]
                }
                res, _ = summarizer.summarize_category_batch("tecnologia", self.sample_articles, cache)

                # La primera nota debe ser del caché
                self.assertEqual(res[0]["summary"], "Resumen previamente cacheado con éxito.")
                self.assertEqual(res[0]["summary_source"], "cache")

                # La segunda nota debió ser enviada a Gemini
                self.assertEqual(res[1]["summary"], "Resumen para el satélite.")
                self.assertEqual(res[1]["summary_source"], "ai")

                # Validar que se guardó en caché
                self.assertIn("https://example.com/satellite-launch", cache)

    def test_ultimo_minuto_picks_top_story(self):
        """Último minuto debe procesar resúmenes y seleccionar la noticia más importante del día."""
        cache = {}
        mock_response = {
            "resumenes": [
                {"id": "0", "resumen": "Avance cuántico fundamental."},
                {"id": "1", "resumen": "Satélite lanzado satisfactoriamente."}
            ],
            "noticia_mas_importante": {
                "titulo": "Avance clave en computación cuántica",
                "categoria": "tecnologia",
                "motivo": "Marca un hito histórico en estabilidad computacional."
            }
        }

        with patch("summarizer.get_gemini_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch("summarizer.call_gemini_batch", return_value=mock_response):
                other_titles = [{"categoria": "economia", "titulo": "Inflación se estabiliza"}]
                res, top_story = summarizer.summarize_category_batch(
                    "ultimo_minuto", self.sample_articles, cache, all_other_titles=other_titles
                )

                self.assertIsNotNone(top_story)
                self.assertEqual(top_story["titulo"], "Avance clave en computación cuántica")
                self.assertIn("hito histórico", top_story["motivo"])
                self.assertEqual(res[0]["summary_source"], "ai")

    def test_error_and_retry_fallback(self):
        """Si Gemini falla en el intento y en el reintento, debe activar el fallback RSS."""
        cache = {}
        with patch("summarizer.get_gemini_client") as mock_client:
            mock_client.return_value = MagicMock()
            with patch("summarizer.call_gemini_batch", return_value=None):
                res, top_story = summarizer.summarize_category_batch("economia", self.sample_articles, cache)
                self.assertIsNone(top_story)
                # Ambas notas deben tener resumen de fallback y no estar vacías
                self.assertTrue(len(res[0]["summary"]) > 10)
                self.assertEqual(res[0]["summary_source"], "fallback")
                self.assertTrue(len(res[1]["summary"]) > 10)
                self.assertEqual(res[1]["summary_source"], "fallback")


if __name__ == "__main__":
    unittest.main()
