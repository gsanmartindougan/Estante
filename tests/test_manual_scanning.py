import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from library import Library


class ManualScanTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'data'),
                                               'XDG_CONFIG_HOME': str(self.root / 'config')})
        environment.start()
        self.addCleanup(environment.stop)
        self.manifest = self.root / 'data/faugus-launcher/games.json'
        self.manifest.parent.mkdir(parents=True)
        self.write_games([{'gameid': 'a', 'title': 'A'}])

    def write_games(self, rows):
        self.manifest.write_text(json.dumps(rows))

    def test_new_library_stays_empty_until_manual_scan_even_after_reopening(self):
        library = Library(home=self.root)
        self.assertEqual(library.games(), [])
        library = Library(home=self.root)
        self.assertEqual(library.games(), [])
        original = self.manifest.read_bytes()
        self.assertEqual(library.scan_faugus(), (1, 1))
        self.assertEqual([game['title'] for game in library.games()], ['A'])
        self.assertEqual(self.manifest.read_bytes(), original)

    def test_changes_are_imported_only_on_scan_and_overrides_survive(self):
        library = Library(home=self.root)
        library.scan_faugus()
        game = library.games()[0]
        library.put(dict(game, banner='/custom.png', categories=['Favorite']))
        self.write_games([{'gameid': 'a', 'title': 'Updated'}, {'gameid': 'b', 'title': 'B'}])
        reopened = Library(home=self.root)
        self.assertEqual([game['title'] for game in reopened.games()], ['A'])
        self.assertEqual(reopened.scan_faugus(), (1, 2))
        updated = next(game for game in reopened.games() if game['gameid'] == 'a')
        self.assertEqual(updated['title'], 'Updated')
        self.assertEqual(updated['banner'], '/custom.png')
        self.assertEqual(updated['categories'], ['Favorite', 'Faugus'])

    def test_legacy_library_is_snapshotted_once(self):
        folder = self.root / 'data/estante'
        folder.mkdir(parents=True)
        (folder / 'library.json').write_text(json.dumps({'games': [], 'overrides': {}}))
        library = Library(home=self.root)
        self.assertEqual(len(library.games()), 1)
        self.write_games([{'gameid': 'b', 'title': 'New'}])
        self.assertEqual([game['title'] for game in Library(home=self.root).games()], ['A'])

    def test_failed_scan_keeps_previous_snapshot(self):
        library = Library(home=self.root)
        library.scan_faugus()
        original = library.file.read_bytes()
        self.manifest.write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):
            library.scan_faugus()
        self.assertEqual(library.file.read_bytes(), original)
        self.assertEqual(len(library.games()), 1)
