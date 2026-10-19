import unittest
from i18n import set_language, get_language
from unittest.mock import patch
from steam_artwork import SteamArtwork


class SteamArtworkTests(unittest.TestCase):
    def setUp(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        set_language('es')

    def test_search_uses_english_when_selected(self):
        set_language('en')
        client = SteamArtwork()
        with patch.object(client, 'request', return_value={'items': []}) as request:
            client.search('Game')
        request.assert_called_once_with('storesearch/', term='Game', l='english', cc='US')

    def test_search_and_screenshots_use_steam_ids(self):
        client = SteamArtwork()
        with patch.object(client, 'request', return_value={'items': [{'id': 42, 'name': 'Game'}]}) as request:
            self.assertEqual(client.search('Game'), [{'id': 42, 'name': 'Game'}])
            request.assert_called_once_with('storesearch/', term='Game', l='spanish', cc='ES')
        with patch.object(client, 'request', return_value={'42': {'success': True, 'data': {
                'screenshots': [{'path_full': 'https://example.com/full.jpg'}, {}]}}}) as request:
            rows = client.screenshots(42)
            self.assertEqual(rows[0]['url'], 'https://example.com/full.jpg')
            self.assertEqual(len(rows), 1)
            request.assert_called_once_with('appdetails', appids='42', l='spanish')

    def test_unavailable_game_reports_error(self):
        with patch.object(SteamArtwork, 'request', return_value={'42': {'success': False}}):
            with self.assertRaises(ValueError):
                SteamArtwork().screenshots(42)
