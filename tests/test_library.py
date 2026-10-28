import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from i18n import set_language, get_language
from unittest.mock import patch, MagicMock

from library import Library, SteamGridDB, launch, launch_command


class LibraryTests(unittest.TestCase):
    def setUp(self):
        previous = get_language()
        self.addCleanup(set_language, previous)
        set_language('es')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'data'),
                                         'XDG_CONFIG_HOME': str(self.root / 'config')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.library = Library(home=self.root)

    def faugus(self, install='native', rows=None):
        directory = next(path for path, kind in self.library.sources if kind == install)
        directory.mkdir(parents=True, exist_ok=True)
        manifest = directory / 'games.json'
        manifest.write_text(json.dumps(rows or [{'gameid': 'test-id', 'title': 'Faugus Test',
                                                'prefix': '/original', 'hidden': False}]))
        self.library.scan_faugus()
        return manifest

    def test_faugus_logo_override_survives_reload_without_changing_manifest(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        game['logo'] = '/custom-logo.png'
        self.library.put(game)
        reopened = Library(home=self.root)
        self.assertEqual(reopened.games()[0]['logo'], '/custom-logo.png')
        self.assertEqual(manifest.read_bytes(), original)

    def test_logo_download_uses_logos_endpoint(self):
        client = SteamGridDB('test', self.root / 'covers')
        with patch.object(client, 'api', return_value=[{'url': 'https://example.org/logo.png'}]) as api, \
             patch.object(client, 'download', return_value='/logo.png'):
            result = client.logo({'title': 'Test', 'steamgriddb_id': 42})
        api.assert_called_once_with('logos/game/42?types=static')
        self.assertEqual(result, {'logo': '/logo.png', 'steamgriddb_id': 42})

    def test_artwork_import_and_download_have_no_size_cap(self):
        client = SteamGridDB('test', self.root / 'covers')
        content = b'x' * 25_000_001
        source = self.root / 'large-image.png'
        source.write_bytes(content)
        self.assertEqual(Path(client.import_artwork(source)).read_bytes(), content)
        response = MagicMock()
        response.__enter__.return_value = response
        from io import BytesIO
        stream = BytesIO(content)
        response.read.side_effect = stream.read
        with patch('library.urlopen', return_value=response):
            target = client.download('https://cdn.steamgriddb.com/large.png')
        self.assertEqual(Path(target).read_bytes(), content)
        self.assertGreater(response.read.call_count, 1)
        self.assertTrue(all(call.args == (256 * 1024,) for call in response.read.call_args_list))

    def test_remove_faugus_persists_across_scan_and_can_be_restored(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        self.library.put(dict(game, banner='/custom.png', categories=['Favorite']))
        self.library.remove(game)
        self.library.remove(game)
        self.assertEqual(self.library.games(), [])
        self.assertEqual(self.library.scan_faugus(), (0, 0))
        reopened = Library(home=self.root)
        self.assertEqual(reopened.games(), [])
        self.assertEqual(reopened.restore_excluded_imports(), 1)
        self.assertEqual(reopened.games()[0]['banner'], '/custom.png')
        self.assertIn('Favorite', reopened.games()[0]['categories'])
        self.assertEqual(manifest.read_bytes(), original)

    def test_remove_local_game_does_not_delete_file_or_other_games(self):
        script = self.root / 'game.sh'
        script.write_text('#!/bin/sh\n')
        first = self.library.local_game('First', str(script))
        second = self.library.local_game('Second', str(script))
        self.library.put(first)
        self.library.put(second)
        self.library.remove(first)
        self.assertTrue(script.is_file())
        self.assertEqual([game['id'] for game in Library(home=self.root).games()], [second['id']])

    def test_direct_import_does_not_write_to_faugus(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        self.assertEqual(game['gameid'], 'test-id')
        self.library.put(dict(game, cover='/custom.png'))
        self.assertEqual(self.library.games()[0]['cover'], '/custom.png')
        self.assertEqual(manifest.read_bytes(), original)
        self.assertFalse(list(self.root.rglob('*.desktop')))

    def test_two_backgrounds_persist_independently_for_faugus_and_local_games(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        faugus = self.library.games()[0]
        self.library.put(dict(faugus, banner='/first.png', banner_secondary='/second.jpg'))
        script = self.root / 'test.sh'
        script.write_text('#!/bin/sh\n')
        local = self.library.local_game('Local', str(script))
        self.library.put(dict(local, banner='/local-first.png', banner_secondary='/local-second.jpg'))
        reopened = Library(home=self.root)
        games = {row['id']: row for row in reopened.games()}
        self.assertEqual(games[faugus['id']]['banner'], '/first.png')
        self.assertEqual(games[faugus['id']]['banner_secondary'], '/second.jpg')
        self.assertEqual(games[local['id']]['banner_secondary'], '/local-second.jpg')
        reopened.put(dict(games[faugus['id']], banner_secondary=''))
        updated = next(row for row in reopened.games() if row['id'] == faugus['id'])
        self.assertEqual(updated['banner'], '/first.png')
        self.assertEqual(updated['banner_secondary'], '')
        self.assertEqual(manifest.read_bytes(), original)

    def test_native_handoff_uses_faugus_game_identifier(self):
        self.faugus()
        with patch('library.shutil.which', return_value='/usr/bin/faugus-launcher'):
            self.assertEqual(launch_command(self.library.games()[0]),
                             (['/usr/bin/faugus-launcher', '--game', 'test-id'], None))

    def test_category_order_and_primary_survive_restart_rename_and_delete(self):
        self.assertIsNone(self.library.primary_category())
        for name in ('A', 'B', 'C'):
            self.library.manage_category(name)
        self.library.move_category('C', -1)
        self.library.move_category('C', -1)
        self.library.set_primary_category('C')
        reopened = Library(home=self.root)
        self.assertEqual(reopened.categories(), ['C', 'A', 'B'])
        self.assertEqual(reopened.primary_category(), 'C')
        reopened.manage_category('Z', 'C')
        self.assertEqual(reopened.categories(), ['Z', 'A', 'B'])
        self.assertEqual(reopened.primary_category(), 'Z')
        reopened.manage_category('', 'Z', delete=True)
        self.assertEqual(reopened.categories(), ['A', 'B'])
        self.assertIsNone(reopened.primary_category())
        reopened.move_category('A', -1)
        self.assertEqual(reopened.categories(), ['A', 'B'])

    def test_bulk_category_assignment_preserves_other_categories_and_faugus_manifest(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        faugus = self.library.games()[0]
        script = self.root / 'game.sh'
        script.write_text('#!/bin/sh\n')
        local = self.library.local_game('Local', str(script))
        self.library.put(dict(faugus, categories=['Other']))
        self.library.put(dict(local, categories=['Other']))
        self.library.manage_category('Selected')
        self.library.set_category_games('Selected', {faugus['id'], local['id']})
        self.library.set_category_games('Selected', {local['id']})
        reopened = Library(home=self.root)
        games = {game['id']: game for game in reopened.games()}
        self.assertEqual(games[faugus['id']]['categories'], ['Other'])
        self.assertEqual(games[local['id']]['categories'], ['Other', 'Selected'])
        self.assertEqual(manifest.read_bytes(), original)
        before = self.library.file.read_bytes()
        with self.assertRaises(ValueError):
            self.library.set_category_games('Selected', {'missing'})
        self.assertEqual(self.library.file.read_bytes(), before)

    def test_categories_persist_for_local_and_faugus(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        self.library.put(dict(game, categories=['Favoritos', 'Pendientes']))
        script = self.root / 'game.sh'
        script.write_text('#!/bin/sh\n')
        local = self.library.local_game('Local', str(script))
        self.library.put(dict(local, categories=['Favoritos']))
        reopened = Library(home=self.root)
        games = {row['id']: row for row in reopened.games()}
        self.assertEqual(games[game['id']]['categories'], ['Favoritos', 'Pendientes'])
        self.assertEqual(games[local['id']]['categories'], ['Favoritos'])
        reopened.put(dict(games[game['id']], categories=[]))
        self.assertEqual(reopened.games()[0]['categories'], [])
        self.assertEqual(manifest.read_bytes(), original)

    def test_manage_categories_preserves_games_and_legacy_assignments(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        self.library.put(dict(game, categories=['Vieja']))
        self.library.manage_category('Vacía')
        self.assertEqual(self.library.categories(), ['Faugus', 'Vacía', 'Vieja'])
        self.library.manage_category('Nueva', 'Vieja')
        self.assertEqual(self.library.games()[0]['categories'], ['Nueva'])
        with self.assertRaises(ValueError):
            self.library.manage_category('nueva')
        with self.assertRaises(ValueError):
            self.library.manage_category('Todos')
        with self.assertRaises(ValueError):
            self.library.manage_category('  ')
        self.library.manage_category('', 'Nueva', delete=True)
        reopened = Library(home=self.root)
        self.assertEqual(reopened.categories(), ['Faugus', 'Vacía'])
        self.assertEqual(reopened.games()[0]['categories'], [])
        self.assertEqual(manifest.read_bytes(), original)

    def test_flatpak_handoff(self):
        self.faugus('flatpak')
        with patch('library.shutil.which', return_value='/usr/bin/flatpak'):
            cmd, cwd = launch_command(self.library.games()[0])
        self.assertEqual(cmd, ['flatpak', 'run', 'io.github.Faugus.faugus-launcher', '--game', 'test-id'])

    def test_hidden_and_duplicate_games(self):
        manifest = self.faugus(rows=[{'gameid': 'a', 'title': 'A', 'hidden': True},
                                    {'gameid': 'b', 'title': 'B'}])
        other = self.library.sources[1][0]
        other.mkdir(parents=True)
        (other / 'games.json').write_bytes(manifest.read_bytes())
        self.assertEqual(self.library.scan_faugus(), (0, 1))
        self.assertEqual([g['title'] for g in self.library.games()], ['B'])
        # Previously imported source-hidden rows must stay invisible as well.
        self.library.state['faugus'].append(dict(gameid='a', title='A', hidden=True,
            id='faugus:native:a', kind='faugus', install='native'))
        self.library.state['overrides']['faugus:native:a'] = {'hidden': False}
        self.assertEqual([g['title'] for g in self.library.games()], ['B'])

    def test_script_launch_preserves_arguments_and_working_directory(self):
        script = self.root / 'my game.sh'
        script.write_text('#!/bin/bash\nprintf "%s\\n" "$PWD" "$@" > result.txt\n')
        game = self.library.local_game('Test', str(script), '--profile "two words" "$(echo no)"')
        self.library.put(game)
        proc = launch(game, self.library.root)
        self.assertEqual(proc.wait(timeout=5), 0)
        self.assertEqual((self.root / 'result.txt').read_text().splitlines(),
                         [str(self.root), '--profile', 'two words', '$(echo no)'])
        loaded = Library(home=self.root)
        self.assertEqual(loaded.games()[0]['arguments'], game['arguments'])
        loaded.remove(game)
        self.assertEqual(loaded.games(), [])
        self.assertTrue(script.is_file())

    def test_appimage_permission_and_parameters(self):
        image = self.root / 'test.AppImage'
        image.touch()
        game = self.library.local_game('App', str(image), '--fullscreen')
        with self.assertRaisesRegex(ValueError, 'permiso'):
            launch_command(game)
        image.chmod(0o700)
        self.assertEqual(launch_command(game)[0], [str(image), '--fullscreen'])

    def test_invalid_arguments_and_working_directory(self):
        script = self.root / 'test.sh'
        script.touch()
        with self.assertRaises(ValueError):
            self.library.local_game('Test', str(script), '"unclosed')
        with self.assertRaises(ValueError):
            self.library.local_game('Test', str(script), cwd=str(self.root / 'missing'))

    def test_broken_manifest_is_reported(self):
        self.faugus().write_text('{broken')
        with self.assertRaises(json.JSONDecodeError):
            self.library.scan_faugus()

    def test_manual_artwork_is_copied_and_custom_url_needs_no_key(self):
        from io import BytesIO
        client = SteamGridDB('', self.root / 'artwork')
        source = self.root / 'source.png'
        source.write_bytes(b'local image')
        cached = Path(client.import_artwork(source))
        source.unlink()
        self.assertEqual(cached.read_bytes(), b'local image')
        with patch('library.urlopen', return_value=BytesIO(b'url image')) as request:
            downloaded = client.download('https://example.com/image.png', custom=True)
            self.assertEqual(Path(downloaded).read_bytes(), b'url image')
            self.assertIsNone(request.call_args.args[0].get_header('Authorization'))
        with self.assertRaises(ValueError):
            client.download('file:///etc/passwd', custom=True)

    def test_steamgriddb_routes_and_missing_key(self):
        client = SteamGridDB('key', self.root)
        with patch.object(client, 'api', return_value=[]) as api:
            client.search('Name / Test')
            api.assert_called_with('search/autocomplete/Name%20%2F%20Test')
            client.grids('42')
            api.assert_called_with('grids/game/42?dimensions=600x900&types=static')
        with self.assertRaises(ValueError):
            SteamGridDB('', self.root).search('test')
        with self.assertRaises(ValueError):
            client.download('https://untrusted.example/cover.png')

    def test_artwork_size_uses_head_without_credentials_or_image_download(self):
        client = SteamGridDB('private-key', self.root)
        response = MagicMock()
        response.__enter__.return_value.headers = {'Content-Length': '1234567'}
        with patch('library.urlopen', return_value=response) as request:
            self.assertEqual(client.artwork_size('https://cdn.steamgriddb.com/original.png'), 1234567)
            sent = request.call_args.args[0]
            self.assertEqual(sent.get_method(), 'HEAD')
            self.assertIsNone(sent.get_header('Authorization'))
            response.__enter__.return_value.read.assert_not_called()
        with patch('library.urlopen', side_effect=OSError('No HEAD')):
            self.assertIsNone(client.artwork_size('https://cdn.steamgriddb.com/original.png'))
        with self.assertRaises(ValueError):
            client.artwork_size('https://untrusted.example/image.png')

    def test_artwork_size_uses_cached_original(self):
        import hashlib
        client = SteamGridDB('', self.root)
        url = 'https://cdn.steamgriddb.com/original.png'
        (self.root / (hashlib.sha256(url.encode()).hexdigest() + '.img')).write_bytes(b'original')
        with patch('library.urlopen') as request:
            self.assertEqual(client.artwork_size(url), 8)
            request.assert_not_called()

    def test_appimage_launch_restores_host_environment(self):
        script = self.root / 'game.sh'
        script.write_text('#!/bin/sh\n')
        game = self.library.local_game('Test', str(script))
        variables = {'ESTANTE_APPDIR': '/tmp/Estante.AppDir', 'PYTHONHOME': '/tmp/bundle/usr',
                     'GI_TYPELIB_PATH': '/tmp/bundle/typelibs', 'GDK_PIXBUF_MODULE_FILE': '/tmp/bundle/cache',
                     'ESTANTE_HOST_PYTHONHOME': '', 'ESTANTE_HOST_GI_TYPELIB_PATH': '/host/typelibs',
                     'ESTANTE_HOST_XDG_DATA_DIRS': '/host/share', 'PATH': '/bundle/bin:/host/bin',
                     'ESTANTE_HOST_PATH': '/host/bin', 'GLYCIN_DATA_DIR': '/bundle/glycin',
                     'ESTANTE_HOST_GLYCIN_DATA_DIR': '', 'ESTANTE_HOST_GDK_PIXBUF_MODULE_FILE': ''}
        with patch.dict(os.environ, variables), patch('library.subprocess.Popen') as popen:
            launch(game, self.library.root)
            env = popen.call_args.kwargs['env']
            self.assertNotIn('PYTHONHOME', env)
            self.assertNotIn('ESTANTE_APPDIR', env)
            self.assertNotIn('GDK_PIXBUF_MODULE_FILE', env)
            self.assertNotIn('GLYCIN_DATA_DIR', env)
            self.assertEqual(env['PATH'], '/host/bin')
            self.assertEqual(env['GI_TYPELIB_PATH'], '/host/typelibs')
            self.assertEqual(env['XDG_DATA_DIRS'], '/host/share')

    def test_qt_bundle_launch_preserves_unmodified_host_environment(self):
        (self.root / 'game.sh').write_text('#!/bin/sh\n')
        game = self.library.local_game('Test', str(self.root / 'game.sh'))
        variables = {'ESTANTE_APPDIR': '/tmp/Estante.AppDir', 'PATH': '/host/bin',
                     'XDG_DATA_DIRS': '/host/share', 'QT_PLUGIN_PATH': '/bundle/plugins',
                     'ESTANTE_HOST_QT_PLUGIN_PATH': '', 'PYTHONPATH': '/bundle/python',
                     'ESTANTE_HOST_PYTHONPATH': '/host/python'}
        with patch.dict(os.environ, variables, clear=True), patch('library.subprocess.Popen') as popen:
            launch(game, self.library.root)
            env = popen.call_args.kwargs['env']
            self.assertEqual(env['PATH'], '/host/bin')
            self.assertEqual(env['XDG_DATA_DIRS'], '/host/share')
            self.assertEqual(env['PYTHONPATH'], '/host/python')
            self.assertNotIn('QT_PLUGIN_PATH', env)
            self.assertFalse(any(key.startswith('ESTANTE_HOST_') for key in env))

    def test_banner_uses_known_id_and_persists_without_changing_faugus(self):
        manifest = self.faugus()
        original = manifest.read_bytes()
        game = self.library.games()[0]
        client = SteamGridDB('key', self.root)
        with patch.object(client, 'api', return_value=[{'url': 'https://cdn.steamgriddb.com/hero.png'}]) as api, \
             patch.object(client, 'download', return_value='/cached/banner.img'):
            result = client.banner(dict(game, steamgriddb_id=42))
        api.assert_called_once_with('heroes/game/42?types=static')
        self.library.put(dict(game, **result))
        loaded = self.library.games()[0]
        self.assertEqual(loaded['banner'], '/cached/banner.img')
        self.assertEqual(loaded['steamgriddb_id'], 42)
        self.assertEqual(manifest.read_bytes(), original)

    def test_square_covers_use_square_dimensions_and_preserve_vertical_cover(self):
        self.faugus()
        game = dict(self.library.games()[0], cover='/vertical.png', steamgriddb_id=42)
        client = SteamGridDB('key', self.root)
        with patch.object(client, 'api', return_value=[{'url': 'square'}]) as api, \
             patch.object(client, 'download', return_value='/square.png'):
            result = client.square_cover(game)
        api.assert_called_once_with('grids/game/42?dimensions=512x512,1024x1024&types=static')
        self.library.put(dict(game, **result))
        saved = self.library.games()[0]
        self.assertEqual(saved['square_cover'], '/square.png')
        self.assertEqual(saved['cover'], '/vertical.png')

    def test_recorded_stats_persist_and_do_not_double_count_faugus(self):
        manifest = self.faugus(rows=[{'gameid': 'a', 'title': 'Faugus', 'playtime': 7200,
                                     'last_played': '2026-10-17T10:00:00'}])
        original = manifest.read_bytes()
        game = self.library.games()[0]
        self.library.record_session(game, 125, '2026-10-18T12:00:00', 0)
        stats = Library(home=self.root).game_stats(game)
        self.assertEqual(stats['seconds'], 7200)
        self.assertEqual(stats['sessions'], 1)
        self.assertEqual(stats['last_seconds'], 125)
        self.assertEqual(stats['last_played'], '2026-10-18T12:00:00')
        self.assertEqual(manifest.read_bytes(), original)
        local = {'id': 'local-stats', 'title': 'Local', 'kind': 'local'}
        self.library.record_session(local, 75, '2026-10-18T12:00:00', 0)
        self.library.record_session(local, 45, '2026-10-18T13:00:00', 1)
        stats = self.library.game_stats(local)
        self.assertEqual(stats['seconds'], 120)
        self.assertEqual(stats['sessions'], 2)
        self.assertEqual(stats['history'][0]['exit_code'], 1)
        self.assertEqual(stats['last_seconds'], 45)

    def test_banner_title_match_and_no_guessing(self):
        client = SteamGridDB('key', self.root)
        with patch.object(client, 'search', return_value=[{'id': 8, 'name': 'Bloodborne'}]), \
             patch.object(client, 'api', return_value=[{'url': 'hero'}]), \
             patch.object(client, 'download', return_value='cached'):
            self.assertEqual(client.banner({'title': 'BloodBorne'})['steamgriddb_id'], 8)
        with patch.object(client, 'search', return_value=[{'id': 9, 'name': 'Bloodborne 2'}]), \
             patch.object(client, 'api') as api:
            self.assertIsNone(client.banner({'title': 'BloodBorne'}))
            api.assert_not_called()

    def test_launch_assigns_unique_inherited_session_tokens_including_flatpak(self):
        with patch('library.launch_command', return_value=(['flatpak', 'run', 'example.Game'], None)), \
             patch('library.subprocess.Popen') as popen:
            first = launch({'kind': 'faugus'}, self.library.root)
            first_token = first.estante_session_token
            args = popen.call_args
            self.assertEqual(args.kwargs['env']['ESTANTE_GAME_SESSION'], first_token)
            self.assertIn('--env=ESTANTE_GAME_SESSION=' + first_token, args.args[0])
            self.assertTrue(args.kwargs['start_new_session'])
            second = launch({'kind': 'faugus'}, self.library.root)
            self.assertNotEqual(first_token, second.estante_session_token)


if __name__ == '__main__':
    unittest.main()
