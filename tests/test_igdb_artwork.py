import json
from io import BytesIO
import unittest
from i18n import set_language, get_language
from unittest.mock import patch
from urllib.error import HTTPError
from igdb_artwork import IGDBArtwork


def response(value):
    return BytesIO(json.dumps(value).encode())


class IGDBArtworkTests(unittest.TestCase):
    def setUp(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        set_language('es')

    def test_authentication_is_cached_and_credentials_stay_out_of_url(self):
        client = IGDBArtwork('client', 'secret')
        with patch('igdb_artwork.urlopen', side_effect=[
                response({'access_token': 'token', 'expires_in': 3600}),
                response([{'id': 1, 'name': 'Bloodborne', 'platforms': [{'name': 'PS4'}]}]),
                response([])]) as request:
            self.assertEqual(client.search('Bloodborne')[0]['platforms'], 'PS4')
            client.search('Other')
        self.assertEqual(request.call_count, 3)
        authentication = request.call_args_list[0].args[0]
        self.assertNotIn('secret', authentication.full_url)
        self.assertIn(b'client_secret=secret', authentication.data)
        self.assertEqual(request.call_args_list[1].args[0].get_header('Authorization'), 'Bearer token')

    def test_missing_credentials_do_not_make_requests(self):
        with patch('igdb_artwork.urlopen') as request:
            with self.assertRaisesRegex(ValueError, 'Ajustes'):
                IGDBArtwork('', '').search('Bloodborne')
            request.assert_not_called()

    def test_authentication_error_does_not_expose_secret(self):
        with patch('igdb_artwork.urlopen', side_effect=HTTPError('url', 400, 'bad', {}, None)):
            with self.assertRaises(ValueError) as error:
                IGDBArtwork('client', 'private-secret').search('Game')
        self.assertNotIn('private-secret', str(error.exception))

    def test_expired_token_is_refreshed_once(self):
        client = IGDBArtwork('id', 'secret')
        client.token, client.expires = 'old', float('inf')
        with patch('igdb_artwork.urlopen', side_effect=[HTTPError('url', 401, '', {}, None),
                response({'access_token': 'new', 'expires_in': 3600}), response([])]):
            self.assertEqual(client.search('Game'), [])
        self.assertEqual(client.token, 'new')

    def test_query_is_escaped_and_images_are_native_16_9(self):
        client = IGDBArtwork('id', 'secret')
        with patch.object(client, 'request', return_value=[]) as request:
            client.search('Game"; fields *;')
            self.assertIn('search "Game\\"; fields *;";', request.call_args.args[0])
        artwork = {'image_id': 'art1', 'width': 1920, 'height': 1080}
        with patch.object(client, 'request', return_value=[{
                'artworks': [artwork, {'image_id': 'portrait', 'width': 900, 'height': 1200}],
                'screenshots': [artwork, {'image_id': 'shot1', 'width': 1280, 'height': 720},
                                {'image_id': 'small', 'width': 640, 'height': 360}]}]):
            rows = client.images(42)
        self.assertEqual(len(rows), 2)
        self.assertIn('t_original/art1.jpg', rows[0]['url'])
        self.assertIn('t_original/shot1.jpg', rows[1]['url'])
