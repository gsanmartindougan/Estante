from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from metadata import GameMetadata
from i18n import get_language, set_language


class MetadataTests(unittest.TestCase):
    def test_metadata_language_and_cache_are_independent(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        entity = {'labels': {'es': {'value': 'Juego'}, 'en': {'value': 'Game'}},
                  'descriptions': {'es': {'value': 'Descripción'}, 'en': {'value': 'Description'}}, 'claims': {}}
        with tempfile.TemporaryDirectory() as directory:
            for language, title in (('es', 'Juego'), ('en', 'Game')):
                set_language(language)
                client = GameMetadata(directory)
                with patch.object(client, 'api', return_value={'entities': {'Q1': entity}}) as api:
                    result = client.fetch('Q1')
                    self.assertEqual(result['title'], title)
                    self.assertTrue(api.call_args.kwargs['languages'].startswith(language))
                with patch.object(client, 'api', side_effect=AssertionError('Cache miss')):
                    self.assertEqual(client.fetch('Q1')['title'], title)
            self.assertEqual(len(list(Path(directory).glob('Q1.*.json'))), 2)

    def test_search_excludes_other_media_and_accepts_game_subclasses(self):
        def typed(identity):
            return {'mainsnak': {'datavalue': {'value': {'id': identity}}}}
        candidates = [('Q100', 'Game', 'Q7889'), ('Q101', 'Comic', 'Q1'),
                      ('Q102', 'News', 'Q2'), ('Q103', 'Edition', 'Q60997816'),
                      ('Q104', 'Expansion', 'Q209163'), ('Q105', 'Game subclass', 'Q3')]
        entities = {identity: {'claims': {'P31': [typed(kind)]}} for identity, _, kind in candidates}
        classes = {'Q1': {}, 'Q2': {}, 'Q3': {'claims': {'P279': [typed('Q7889')]}}}
        with tempfile.TemporaryDirectory() as directory:
            client = GameMetadata(directory)
            with patch.object(client, 'api', side_effect=[
                    {'search': [{'id': identity, 'label': name} for identity, name, _ in candidates]},
                    {'entities': entities}, {'entities': classes}]):
                results = client.search('Game')
        self.assertEqual([row['name'] for row in results], ['Game', 'Edition', 'Expansion', 'Game subclass'])

    def test_fields_dates_and_cached_response(self):
        def claim(value):
            return {'mainsnak': {'datavalue': {'value': value}}}
        entity = {'labels': {'en': {'value': 'Example Game'}},
                  'descriptions': {'es': {'value': 'videojuego de acción'}},
                  'claims': {'P178': [claim({'id': 'Q10'})],
                             'P123': [claim({'id': 'Q11'})],
                             'P136': [claim({'id': 'Q12'})],
                             'P400': [claim({'id': 'Q13'})],
                             'P577': [claim({'time': '+2015-03-24T00:00:00Z', 'precision': 11}),
                                      claim({'time': '+2015-03-27T00:00:00Z', 'precision': 11})]}}
        labels = {identity: {'labels': {'en': {'value': label}}}
                  for identity, label in [('Q10', 'Studio'), ('Q11', 'Publisher'),
                                          ('Q12', 'Action'), ('Q13', 'Console')]}
        with tempfile.TemporaryDirectory() as directory:
            client = GameMetadata(directory)
            with patch.object(client, 'api', side_effect=[{'entities': {'Q1': entity}}, {'entities': labels}]):
                result = client.fetch('Q1')
            self.assertEqual(result['developers'], ['Studio'])
            self.assertEqual(result['publishers'], ['Publisher'])
            self.assertEqual(result['release_date'], '2015-03-24')
            self.assertEqual(result['genres'], ['Action'])
            self.assertEqual(result['platforms'], ['Console'])
            self.assertEqual(result['source'], 'https://www.wikidata.org/wiki/Q1')
            with patch.object(client, 'api') as api:
                self.assertEqual(client.fetch('Q1'), result)
                api.assert_not_called()

    def test_missing_fields_are_empty_and_invalid_identifier_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            client = GameMetadata(directory)
            with patch.object(client, 'api', return_value={'entities': {'Q1': {}}}):
                result = client.fetch('Q1')
            self.assertEqual(result['developers'], [])
            self.assertEqual(result['release_date'], '')
            with self.assertRaises(ValueError):
                client.fetch('../bad')
