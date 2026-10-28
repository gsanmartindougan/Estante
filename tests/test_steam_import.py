import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from library import Library, launch_command
from steam_import import read_vdf, discover_steam, is_faugus_steam


def vdf(values):
    def quoted(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'
    return '\n'.join(quoted(key) + ('\n{\n' + vdf(value) + '\n}' if isinstance(value, dict) else '\t' + quoted(value))
                     for key, value in values.items())


class SteamImportTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.data = self.home / 'data'
        self.native = self.data / 'Steam'
        self.native.mkdir(parents=True)
        context = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.data), 'XDG_CONFIG_HOME': str(self.home / 'config')})
        context.start()
        self.addCleanup(context.stop)

    def manifest(self, root, appid, title, installed=True):
        directory = root / 'steamapps/common' / title
        directory.mkdir(parents=True)
        manifest = root / 'steamapps' / f'appmanifest_{appid}.acf'
        manifest.write_text(vdf({'AppState': {'appid': appid, 'name': title,
            'installdir': title, 'StateFlags': 4 if installed else 2}}))
        return manifest

    def test_native_external_libraries_aliases_and_cached_artwork(self):
        manifest = self.manifest(self.native, '42', 'Game')
        external = self.home / 'Other Disk/SteamLibrary'
        self.manifest(external, '43', 'Second Game')
        self.manifest(external, '42', 'Game')
        registry = self.native / 'steamapps/libraryfolders.vdf'
        registry.write_text(vdf({'libraryfolders': {'0': {'path': self.native}, '1': {'path': external}}}))
        alias = self.home / '.steam/steam'
        alias.parent.mkdir()
        alias.symlink_to(self.native, target_is_directory=True)
        cache = self.native / 'appcache/librarycache/42'
        cache.mkdir(parents=True)
        (cache / 'library_600x900.jpg').touch()
        original = manifest.read_bytes(), registry.read_bytes()
        games = discover_steam(self.home, self.data)
        self.assertEqual([game['id'] for game in games], ['steam:42', 'steam:43'])
        self.assertEqual(games[0]['install'], 'native')
        self.assertEqual(games[0]['cover'], str(cache / 'library_600x900.jpg'))
        self.assertEqual((manifest.read_bytes(), registry.read_bytes()), original)

    def test_flatpak_and_legacy_registry(self):
        flatpak = self.home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        external = self.home / 'External'
        self.manifest(external, '42', 'Game')
        (flatpak / 'config').mkdir(parents=True)
        (flatpak / 'config/libraryfolders.vdf').write_text(vdf({'LibraryFolders': {'1': str(external)}}))
        games = discover_steam(self.home, self.data)
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]['install'], 'flatpak')

    def test_tools_incomplete_and_missing_installations_are_skipped(self):
        self.manifest(self.native, '42', 'Game')
        self.manifest(self.native, '43', 'Proton Experimental')
        self.manifest(self.native, '44', 'Steam Linux Runtime 4.0')
        self.manifest(self.native, '45', 'Steamworks Common Redistributables')
        self.manifest(self.native, '46', 'Downloading Game', installed=False)
        removed = self.manifest(self.native, '47', 'Removed Game')
        (self.native / 'steamapps/common/Removed Game').rmdir()
        self.assertTrue(removed.is_file())
        self.assertEqual([game['id'] for game in discover_steam(self.home, self.data)], ['steam:42'])

    def test_manual_scan_persists_and_preserves_override_and_categories(self):
        manifest = self.manifest(self.native, '42', 'Game')
        original = manifest.read_bytes()
        library = Library(home=self.home)
        self.assertEqual(library.games(), [])
        self.assertEqual(library.scan_steam(), (1, 1))
        game = library.games()[0]
        self.assertEqual(game['categories'], ['Steam'])
        library.put(dict(game, banner='/custom.png', categories=['Favorite', 'Steam']))
        library.scan_steam()
        reopened = Library(home=self.home)
        self.assertEqual(len(reopened.games()), 1)
        self.assertEqual(reopened.games()[0]['banner'], '/custom.png')
        self.assertEqual(reopened.games()[0]['categories'], ['Favorite', 'Steam'])
        reopened.manage_category('Other')
        reopened.set_category_games('Other', {'steam:42'})
        self.assertIn('Other', reopened.games()[0]['categories'])
        self.assertEqual(manifest.read_bytes(), original)

    def test_faugus_steam_entries_are_skipped_without_title_heuristics(self):
        library = Library(home=self.home)
        manifest = library.sources[0][0] / 'games.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps([
            {'gameid': 'steam', 'title': 'Game', 'runner': 'Steam', 'path': '42'},
            {'gameid': 'uri', 'title': 'Other', 'path': 'steam://rungameid/43'},
            {'gameid': 'normal', 'title': 'Normal', 'runner': 'Proton-GE', 'path': '/games/Game_Steam.exe'}]))
        original = manifest.read_bytes()
        self.assertEqual(library.scan_faugus(), (1, 1))
        self.assertEqual(library.games()[0]['gameid'], 'normal')
        self.assertEqual(library.games()[0]['categories'], ['Faugus'])
        self.assertEqual(manifest.read_bytes(), original)
        self.assertFalse(is_faugus_steam({'steamgriddb_id': 42, 'steam_user': '123', 'runner': 'Proton-GE'}))

    def test_existing_faugus_steam_snapshot_is_omitted(self):
        library = Library(home=self.home)
        library.state['faugus'] = [{'id': 'faugus:native:42', 'kind': 'faugus',
                                    'gameid': '42', 'title': 'Game', 'runner': 'Steam', 'path': '42'}]
        library.save()
        self.assertEqual(Library(home=self.home).games(), [])

    def test_launch_uses_correct_steam_client_and_validates_id(self):
        with patch('library.shutil.which', return_value='/usr/bin/steam'):
            command, cwd = launch_command({'kind': 'steam', 'steam_appid': '42', 'install': 'native'})
        self.assertEqual(command, ['/usr/bin/steam', '-silent', '-applaunch', '42'])
        self.assertIsNone(cwd)
        with patch('library.shutil.which', return_value='/usr/bin/flatpak'):
            command, _ = launch_command({'kind': 'steam', 'steam_appid': '42', 'install': 'flatpak'})
        self.assertEqual(command, ['flatpak', 'run', 'com.valvesoftware.Steam', '-silent', '-applaunch', '42'])
        with self.assertRaises(ValueError):
            launch_command({'kind': 'steam', 'steam_appid': '42; echo unsafe'})

    def test_native_and_flatpak_same_app_are_not_duplicated(self):
        self.manifest(self.native, '42', 'Game')
        flatpak = self.home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'
        self.manifest(flatpak, '42', 'Game')
        self.manifest(flatpak, '43', 'Another Game')
        games = discover_steam(self.home, self.data)
        self.assertEqual(len(games), 2)
        self.assertEqual(next(game['install'] for game in games if game['steam_appid'] == '42'), 'native')

    def test_removed_steam_game_stays_removed_and_restores_with_artwork(self):
        manifest = self.manifest(self.native, '42', 'Game')
        original = manifest.read_bytes()
        library = Library(home=self.home)
        library.scan_steam()
        game = library.games()[0]
        library.put(dict(game, logo='/custom-logo.png'))
        library.remove(game)
        self.assertEqual(library.scan_steam(), (0, 0))
        reopened = Library(home=self.home)
        self.assertEqual(reopened.games(), [])
        self.assertEqual(reopened.restore_excluded_imports(), 1)
        self.assertEqual(reopened.games()[0]['logo'], '/custom-logo.png')
        self.assertEqual(manifest.read_bytes(), original)

    def test_vdf_preserves_quotes_unicode_and_comments(self):
        file = self.home / 'test.vdf'
        file.write_text('// comment\n' + vdf({'AppState': {'name': 'Juego "Especial"', 'path': '/ruta/á'}}))
        self.assertEqual(read_vdf(file)['appstate']['name'], 'Juego "Especial"')
        file.write_text('"AppState" { "name" "Game"')
        with self.assertRaises(ValueError):
            read_vdf(file)
