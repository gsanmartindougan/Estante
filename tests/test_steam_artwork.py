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

    def test_metadata_reads_localized_date_and_preserves_missing_values(self):
        data={'name':'Game','short_description':'<p>Una &amp; otra aventura.</p>',
              'developers':['Studio'],'publishers':['Publisher'],'genres':[{'description':'Acción'}],
              'platforms':{'windows':True,'linux':True},'release_date':{'date':'19 AGO 2024'}}
        with patch.object(SteamArtwork,'request',return_value={'42':{'success':True,'data':data}}):
            metadata=SteamArtwork().metadata(42)
        self.assertEqual(metadata['release_date'],'2024-08-19')
        self.assertEqual(metadata['synopsis'],'Una & otra aventura.')
        self.assertEqual(metadata['developers'],['Studio'])
        self.assertEqual(metadata['platforms'],['Microsoft Windows','Linux'])
        self.assertEqual(metadata['source'],'https://store.steampowered.com/app/42/')
        with patch.object(SteamArtwork,'request',return_value={'42':{'success':True,'data':{'name':'Game','release_date':{'date':'Próximamente'}}}}):
            metadata=SteamArtwork().metadata(42)
        self.assertNotIn('release_date',metadata)
        self.assertNotIn('developers',metadata)
