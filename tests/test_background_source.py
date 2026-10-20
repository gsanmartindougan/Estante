import unittest
from backgrounds import (background_assets, initial_background_settings,
                         DEFAULT_BACKGROUND, BUNDLED_BACKGROUNDS, resolve_background)


class BackgroundSourceTests(unittest.TestCase):
    def test_default_preserves_both_game_backgrounds(self):
        game = {'banner': 'first.png', 'banner_secondary': 'second.png'}
        self.assertEqual(background_assets({}, game), ('first.png', 'second.png'))

    def test_global_ignores_game_assets_without_modifying_them(self):
        game = {'banner': 'first.png', 'banner_secondary': 'second.png'}
        settings = {'background_source': 'global', 'global_background': 'shared.png'}
        self.assertEqual(background_assets(settings, game), ('shared.png', ''))
        settings['background_source'] = 'game'
        self.assertEqual(background_assets(settings, game), ('first.png', 'second.png'))

    def test_missing_global_does_not_use_game_background(self):
        self.assertEqual(background_assets({'background_source': 'global'}, {'banner': 'game.png'}), ('', ''))

    def test_first_run_uses_shipped_default(self):
        settings = initial_background_settings({}, first_run=True)
        self.assertEqual(settings['global_background'], DEFAULT_BACKGROUND)
        self.assertEqual(settings['background_source'], 'global')
        self.assertTrue(__import__('pathlib').Path(background_assets(settings, {})[0]).is_file())
        self.assertEqual(len(BUNDLED_BACKGROUNDS), 6)

    def test_existing_preferences_are_preserved(self):
        settings = {'background_source': 'game', 'global_background': '/custom.png'}
        self.assertEqual(initial_background_settings(settings), settings)
        self.assertEqual(initial_background_settings({}), {})

    def test_bundled_identifier_cannot_escape_assets(self):
        self.assertEqual(resolve_background('bundled:../../estante.py'), '')

    def test_renamed_background_preserves_existing_selection(self):
        self.assertEqual(resolve_background('bundled:wallhaven-dgx11m_2560x1440.png'),
                         resolve_background('bundled:6.png'))
        self.assertEqual({path.stem for path in BUNDLED_BACKGROUNDS},
                         {str(number) for number in range(1, 7)})
