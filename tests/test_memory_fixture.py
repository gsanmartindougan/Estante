from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from tools.memory_fixture import populate_test_games


class MemoryFixtureTests(TestCase):
    def test_hundred_games_have_independent_artwork_and_no_real_launch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'original.png'
            image.write_bytes(b'original image bytes')
            original = dict(id='original', title='Source', kind='faugus', cover=str(image),
                            path='/real/game', arguments='--real', categories=['Private'])
            library = SimpleNamespace(root=root, games=lambda: [original], save=Mock())
            games = populate_test_games(library, 100)
            self.assertEqual(len(games), 100)
            self.assertEqual(len({game['id'] for game in games}), 100)
            self.assertEqual(len({game['cover'] for game in games}), 100)
            self.assertEqual(original['path'], '/real/game')
            self.assertEqual(original['categories'], ['Private'])
            for game in games:
                copy = Path(game['cover'])
                self.assertEqual(copy.read_bytes(), image.read_bytes())
                self.assertNotEqual(copy.stat().st_ino, image.stat().st_ino)
                self.assertNotEqual(game['path'], '/real/game')
                self.assertEqual(game['arguments'], '')
                self.assertEqual(game['categories'], [])
            library.save.assert_called_once()
            self.assertEqual(library.state['faugus'], [])
            Path(games[0]['cover']).write_bytes(b'edited test copy')
            self.assertEqual(image.read_bytes(), b'original image bytes')

    def test_empty_library_and_invalid_count_are_rejected(self):
        library = SimpleNamespace(games=lambda: [], save=Mock())
        with self.assertRaises(ValueError):
            populate_test_games(library, 100)
        library.games = lambda: [{'title': 'Source'}]
        with self.assertRaises(ValueError):
            populate_test_games(library, 0)
        library.save.assert_not_called()
