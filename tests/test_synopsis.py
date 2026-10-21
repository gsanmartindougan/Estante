from unittest import TestCase
from unittest.mock import patch
from steam_artwork import SteamArtwork


class SynopsisTests(TestCase):
    def test_steam_synopsis_is_plain_text_and_uses_game_details(self):
        client = SteamArtwork()
        with patch.object(client, 'request', return_value={'10': {'success': True, 'data': {
                'short_description': 'Explore <b>the world</b> &amp; survive.<br> A new adventure.'}}}) as request:
            self.assertEqual(client.synopsis(10), 'Explore the world & survive. A new adventure.')
        self.assertEqual(request.call_args.args, ('appdetails',))
        self.assertEqual(request.call_args.kwargs['appids'], '10')

    def test_missing_synopsis_is_reported_without_inventing_one(self):
        client = SteamArtwork()
        for result in ({}, {'10': {'success': False}}, {'10': {'success': True, 'data': {}}}):
            with patch.object(client, 'request', return_value=result):
                with self.assertRaises(ValueError):
                    client.synopsis(10)
