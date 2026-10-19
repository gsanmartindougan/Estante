import os
import unittest
from unittest.mock import patch

from i18n import ENGLISH, get_language, set_language, system_language, tr
from library import Library
from updates import update_available


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.previous = get_language()
        self.addCleanup(set_language, self.previous)

    def test_default_uses_spanish_only_for_spanish_systems(self):
        for locale, expected in [('es_ES.UTF-8', 'es'), ('es_MX', 'es'), ('es-AR', 'es'),
                                 ('en_US.UTF-8', 'en'), ('fr_FR.UTF-8', 'en'), ('de_DE', 'en'),
                                 ('C', 'en'), ('C.UTF-8', 'en'), ('', 'en')]:
            with self.subTest(locale=locale), patch.dict(os.environ, {'LANG': locale}, clear=True):
                set_language('system')
                self.assertEqual(get_language(), expected)
                self.assertEqual(system_language(), expected)

    def test_locale_precedence_and_manual_selection(self):
        with patch.dict(os.environ, {'LANG': 'en_US', 'LC_MESSAGES': 'es_ES', 'LC_ALL': 'fr_FR'}, clear=True):
            set_language('system')
            self.assertEqual(get_language(), 'en')
            set_language('es')
            self.assertEqual(get_language(), 'es')
            set_language('en')
            self.assertEqual(get_language(), 'en')
        with patch.dict(os.environ, {'LANGUAGE': 'es:en', 'LANG': 'en_US'}, clear=True):
            set_language('system')
            self.assertEqual(get_language(), 'es')

    def test_catalog_covers_both_languages_and_preserves_unknown_content(self):
        for language in ('es', 'en'):
            set_language(language)
            for spanish, english in ENGLISH.items():
                self.assertEqual(tr(spanish), english if language == 'en' else spanish)
            self.assertEqual(tr('My custom category'), 'My custom category')
            self.assertEqual(tr('Bloodborne'), 'Bloodborne')

    def test_errors_and_formatted_ui_text_are_translated(self):
        set_language('en')
        with self.assertRaisesRegex(ValueError, 'name for the game'):
            Library.local_game('', '/tmp/game.sh')
        self.assertIn('In-app updates', update_available({}))
        self.assertEqual(tr('No se pudo leer la biblioteca: ') + 'error', 'Could not read the library: error')
        self.assertIn('D-pad', tr('← ↑ ↓ → / Cruceta: mover · LB/RB: letra · LT/RT: categoría · Enter / A: abrir · Esc / B: volver · Ctrl+F / Select: buscar'))
