from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock
from scraping import scrape_game, apply_scrape_patch, ARTWORK_FIELDS


class ScrapingTests(TestCase):
    def client(self):
        client = Mock()
        client.resolve_game_id.return_value = 42
        client.grids.return_value = [{'url': 'cover'}]
        client.logos.return_value = [{'url': 'logo'}]
        client.heroes.return_value = [{'url': 'first'}, {'url': 'second'}]
        client.download.side_effect = lambda url: '/cache/' + url
        return client

    def test_fill_preserves_existing_images_and_populates_missing_secondary(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'image.png'
            path.touch()
            game = dict(id='game', title='Game', **{field: str(path) for field in ARTWORK_FIELDS})
            client = self.client()
            self.assertEqual(scrape_game(game, client), ({}, []))
            client.resolve_game_id.assert_not_called()
            game['banner_secondary'] = '/missing.png'
            result, errors = scrape_game(game, client)
            self.assertEqual(result, {'banner_secondary': '/cache/second', 'steamgriddb_id': 42})
            self.assertEqual(errors, [])
            client.download.assert_called_once_with('second')
            client.grids.assert_not_called()

    def test_replace_refreshes_all_images_and_keeps_unavailable_data(self):
        game = dict(id='game', title='Game', **{field: '/old' for field in ARTWORK_FIELDS})
        client = self.client()
        result, errors = scrape_game(game, client, replace=True)
        self.assertEqual(set(result), {*ARTWORK_FIELDS, 'steamgriddb_id'})
        self.assertEqual(errors, [])
        client = self.client()
        client.heroes.return_value = []
        result, _ = scrape_game(game, client, replace=True)
        self.assertNotIn('banner', result)
        self.assertNotIn('banner_secondary', result)

    def test_image_failure_does_not_erase_existing_data_or_stop_other_sources(self):
        client = self.client()
        client.grids.side_effect = RuntimeError('failure')
        result, errors = scrape_game({'id': 'game', 'title': 'Game'}, client, replace=True)
        self.assertNotIn('cover', result)
        self.assertEqual(result['logo'], '/cache/logo')
        self.assertTrue(errors)

    def test_fill_metadata_preserves_manual_fields_and_replace_updates_them(self):
        game = {'id': 'game', 'title': 'Game', 'metadata': {'entity_id': 'Q1', 'developers': ['Manual']}}
        metadata = Mock()
        metadata.fetch.return_value = {'entity_id': 'Q1', 'developers': ['Source'], 'release_date': '2020-01-01'}
        result, _ = scrape_game(game, metadata=metadata)
        self.assertEqual(result['metadata']['developers'], ['Manual'])
        self.assertEqual(result['metadata']['release_date'], '2020-01-01')
        result, _ = scrape_game(game, metadata=metadata, replace=True)
        self.assertEqual(result['metadata']['developers'], ['Source'])
        metadata.search.assert_not_called()

    def test_ambiguous_matches_are_skipped(self):
        metadata = Mock()
        metadata.search.return_value = [{'id': 'Q1', 'name': 'Game'}, {'id': 'Q2', 'name': 'Game'}]
        self.assertEqual(scrape_game({'title': 'Game'}, metadata=metadata), ({}, []))
        metadata.fetch.assert_not_called()
        client = self.client()
        client.resolve_game_id.return_value = None
        self.assertEqual(scrape_game({'title': 'Game'}, artwork=client), ({}, []))
        client.download.assert_not_called()

    def test_manual_edits_made_during_scraping_win(self):
        original = {'id': 'game', 'banner': '/old', 'cover': '/oldcover'}
        current = dict(original, banner='/manual', categories=['Favorite'])
        result = apply_scrape_patch(current, original, {'banner': '/scraped', 'cover': '/newcover'})
        self.assertEqual(result['banner'], '/manual')
        self.assertEqual(result['cover'], '/newcover')
        self.assertEqual(result['categories'], ['Favorite'])

    def test_selected_formats_and_secondary_background_are_independent(self):
        for field, url in (('cover', 'cover'), ('square_cover', 'cover'), ('banner_secondary', 'second')):
            client = self.client()
            result, errors = scrape_game({'title': 'Game'}, client, fields={field})
            self.assertEqual(set(result), {field, 'steamgriddb_id'})
            self.assertEqual(result[field], '/cache/' + url)
            self.assertEqual(errors, [])
            if field == 'square_cover':
                client.grids.assert_called_once_with(42, square=True)
            elif field == 'cover':
                client.grids.assert_called_once_with(42)
            else:
                client.heroes.assert_called_once_with(42)
                client.grids.assert_not_called()
        client = self.client()
        self.assertEqual(scrape_game({'title': 'Game'}, client, fields=set()), ({}, []))
        client.resolve_game_id.assert_not_called()
