"""Persistence and interrupted-transfer guarantees for backend optimizations."""
import hashlib
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from library import Library, SteamGridDB
from scraping import apply_scrape_results


class BackendBatchTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(home=self.root, data_dir=self.root/'library')

    def test_scraping_indexes_and_saves_once_preserving_manual_edits_and_deleted_games(self):
        originals = [dict(id=str(i), title=str(i), kind='custom', cover='old') for i in range(100)]
        self.library.put_many(originals)
        self.library.put(dict(originals[0], cover='manual'))
        self.library.state['games'] = [g for g in self.library.state['games'] if g['id'] != '0']
        self.library.put(dict(originals[1], cover='manual'))
        results = [(game, {'cover': 'new'}, ['failure']*2) for game in originals]
        with patch.object(self.library, 'games', wraps=self.library.games) as games, \
             patch.object(self.library, 'save', wraps=self.library.save) as save:
            changed, failures, messages = apply_scrape_results(self.library, results)
        self.assertEqual(games.call_count, 1)
        self.assertEqual(save.call_count, 1)
        self.assertEqual((changed, failures, len(messages)), (98, 200, 5))
        reopened = Library(home=self.root, data_dir=self.library.root)
        rows = {g['id']: g for g in reopened.games()}
        self.assertNotIn('0', rows)
        self.assertEqual(rows['1']['cover'], 'manual')
        self.assertEqual(rows['99']['cover'], 'new')

    def test_mixed_batch_persists_import_overrides_and_custom_order(self):
        first = dict(id='a', title='A', kind='custom')
        second = dict(id='b', title='B', kind='custom')
        self.library.put_many([first, second])
        self.library.put_many([dict(first, cover='new'),
                               dict(id='steam:1', title='Steam', kind='steam', cover='import', categories=['Fav'])])
        reopened = Library(home=self.root, data_dir=self.library.root)
        self.assertEqual([g['id'] for g in reopened.state['games']], ['b', 'a'])
        self.assertEqual(reopened.state['overrides']['steam:1'], {'cover': 'import', 'categories': ['Fav']})

    def test_empty_batch_does_not_save_and_failed_save_restores_model(self):
        previous = self.library.state
        with patch.object(self.library, 'save', side_effect=OSError('disk full')) as save:
            self.library.put_many([])
            save.assert_not_called()
            with self.assertRaises(OSError):
                self.library.put_many([dict(id='x', title='X', kind='steam', cover='x')])
        self.assertIs(self.library.state, previous)
        self.assertNotIn('x', previous['overrides'])

    def test_interrupted_download_never_publishes_partial_file(self):
        client = SteamGridDB('', self.root/'artwork')
        stream = BytesIO(b'first chunk')
        with patch.object(stream, 'read', side_effect=[b'first chunk', OSError('connection lost')]), \
             patch('library.urlopen', return_value=stream):
            with self.assertRaises(OSError):
                client.download('https://cdn.steamgriddb.com/interrupted.png')
        self.assertEqual(list(client.cache.iterdir()), [])

    def test_import_keeps_content_hash_and_cleans_failed_atomic_replacement(self):
        client = SteamGridDB('', self.root/'artwork')
        source = self.root/'source.png'
        source.write_bytes(b'original image')
        imported = Path(client.import_artwork(source))
        self.assertEqual(imported.stem, hashlib.sha256(source.read_bytes()).hexdigest())
        with patch('library.os.replace', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                client.import_artwork(source)
        self.assertEqual(imported.read_bytes(), b'original image')
        self.assertEqual(list(client.cache.iterdir()), [imported])
