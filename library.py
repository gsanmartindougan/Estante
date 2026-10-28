"""Local library, direct Faugus handoff and optional SteamGridDB artwork."""
from steam_import import discover_steam, is_faugus_steam
from heroic_import import discover_heroic, launch_url
from i18n import tr
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen
import uuid


def read_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


class Library:
    def __init__(self, home=None, data_dir=None):
        self.home = Path(home or Path.home())
        data = Path(os.environ.get('XDG_DATA_HOME', self.home / '.local/share'))
        config = Path(os.environ.get('XDG_CONFIG_HOME', self.home / '.config'))
        self.steam_data = data
        self.heroic_config = config
        self.root = Path(data_dir or data / 'estante')
        self.root.mkdir(parents=True, exist_ok=True)
        self.file = self.root / 'library.json'
        self.state = read_json(self.file, {'games': [], 'overrides': {}})
        self.sources = [
            (data / 'faugus-launcher', 'native'),
            (config / 'faugus-launcher', 'native'),
            (self.home / '.var/app/io.github.Faugus.faugus-launcher/data/faugus-launcher', 'flatpak'),
            (self.home / '.var/app/io.github.Faugus.faugus-launcher/config/faugus-launcher', 'flatpak'),
        ]
        if 'faugus' not in self.state:
            # Snapshot the legacy library once; new installations start unscanned.
            self.state['faugus'] = self.discover_faugus() if self.file.exists() else []
            self.save()
        if not self.state.get('source_categories_initialized'):
            self.assign_source_category([game for game in self.state['faugus'] if not is_faugus_steam(game)], 'Faugus')
            self.assign_source_category(self.state.get('steam', []), 'Steam')
            self.state['source_categories_initialized'] = True
            self.save()

    @property
    def state(self):
        if self._state is None:
            self._state = read_json(self.file, {'games': [], 'overrides': {}})
        return self._state

    @state.setter
    def state(self, value):
        self._state = value

    def release_state(self):
        """Unload the saved model; the next access reloads it without scanning."""
        self._state = None

    def save(self):
        fd, name = tempfile.mkstemp(dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.state, stream, ensure_ascii=False, indent=2)
            os.replace(name, self.file)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def discover_faugus(self):
        games, seen = [], set()
        for directory, install in self.sources:
            for row in read_json(directory / 'games.json', []):
                if not isinstance(row, dict) or not row.get('gameid') or is_faugus_steam(row):
                    continue
                identity = f"faugus:{install}:{row['gameid']}"
                if identity in seen:
                    continue
                seen.add(identity)
                game = dict(row, id=identity, kind='faugus', install=install)
                cover = Path(str(row.get('cover') or '')).expanduser()
                if not cover.is_file():
                    cover = directory / 'covers' / f"{row['gameid']}.png"
                game['cover'] = str(cover) if cover.is_file() else ''
                if not game.get('hidden'):
                    games.append(game)
        return sorted(games, key=lambda g: g['title'].casefold())

    def scan_faugus(self):
        excluded = set(self.state.get('excluded_imports', []))
        discovered = [game for game in self.discover_faugus() if game['id'] not in excluded]
        imported = {game['id']: game for game in self.state.get('faugus', []) if not is_faugus_steam(game)}
        added = sum(game['id'] not in imported for game in discovered)
        imported.update({game['id']: game for game in discovered})
        self.state['faugus'] = list(imported.values())
        self.assign_source_category(self.state['faugus'], 'Faugus')
        self.save()
        return added, len(discovered)

    def assign_source_category(self, games, category):
        if not games:
            return
        registered = self.state.setdefault('categories', [])
        if category not in registered:
            registered.append(category)
        for game in games:
            override = self.state['overrides'].setdefault(game['id'], {})
            override['categories'] = list(dict.fromkeys([*override.get('categories', game.get('categories', [])), category]))

    def scan_steam(self):
        excluded = set(self.state.get('excluded_imports', []))
        discovered = [game for game in discover_steam(self.home, self.steam_data) if game['id'] not in excluded]
        imported = {game['id']: game for game in self.state.get('steam', [])}
        added = sum(game['id'] not in imported for game in discovered)
        imported.update({game['id']: game for game in discovered})
        self.state['steam'] = list(imported.values())
        self.assign_source_category(self.state['steam'], 'Steam')
        self.save()
        return added, len(discovered)

    def scan_heroic(self):
        excluded = set(self.state.get('excluded_imports', []))
        discovered = [game for game in discover_heroic(self.home, self.heroic_config) if game['id'] not in excluded]
        previous = {game['id']: game for game in self.state.get('heroic', [])}
        added = sum(game['id'] not in previous for game in discovered)
        # Unlike live scans, imported entries are snapshots. Keep edits in overrides.
        self.state['heroic'] = discovered
        self.assign_source_category(discovered, 'Heroic')
        self.save()
        return added, len(discovered)

    def games(self):
        games = []
        excluded = set(self.state.get('excluded_imports', []))
        for row in self.state.get('faugus', []) + self.state.get('steam', []) + self.state.get('heroic', []):
            if row['id'] in excluded:
                continue
            if row['kind'] == 'faugus' and is_faugus_steam(row):
                continue
            game = dict(row)
            game.update(self.state['overrides'].get(game['id'], {}))
            if not row.get('hidden') and not game.get('hidden'):
                games.append(game)
        games.extend(dict(row) for row in self.state['games'])
        return sorted(games, key=lambda game: game['title'].casefold())

    def put(self, game):
        self.put_many([game])

    def put_many(self, games):
        """Apply a batch with one atomic save and no repeated custom-game scans."""
        custom = {game['id']: game for game in self.state['games']}
        overrides = dict(self.state['overrides'])
        changed = False
        for game in games:
            changed = True
            if game['kind'] in ('faugus', 'steam', 'heroic'):
                overrides[game['id']] = {
                    key: game[key] for key in ('cover', 'square_cover', 'logo', 'banner', 'banner_secondary', 'steamgriddb_id', 'metadata', 'categories') if key in game}
            else:
                custom.pop(game['id'], None)
                custom[game['id']] = game
        if changed:
            previous = self.state
            self.state = {**previous, 'games': list(custom.values()), 'overrides': overrides}
            try:
                self.save()
            except Exception:
                self.state = previous
                raise

    def categories(self):
        names = list(self.state.get('categories', []))
        for game in self.state['games'] + list(self.state['overrides'].values()):
            names.extend(game.get('categories', []))
        available = set(names)
        ordered = list(dict.fromkeys(name for name in self.state.get('category_order', []) if name in available))
        return ordered + sorted(available - set(ordered), key=str.casefold)

    def manage_category(self, name, previous=None, delete=False):
        names = self.categories()
        name = name.strip()
        if previous is not None and previous not in names:
            raise ValueError(tr('La categoría ya no existe.'))
        if not delete:
            if not name or name.casefold() in ('todos', 'all'):
                raise ValueError(tr('Escribe un nombre distinto de «Todos».'))
            if any(item != previous and item.casefold() == name.casefold() for item in names):
                raise ValueError(tr('Ya existe una categoría con ese nombre.'))
        if previous is not None:
            names.remove(previous)
            for game in self.state['games'] + list(self.state['overrides'].values()):
                if previous in game.get('categories', []):
                    game['categories'] = list(dict.fromkeys(name if item == previous else item
                        for item in game['categories'] if not (delete and item == previous)))
        if not delete:
            names.append(name)
        if previous is not None:
            self.state['category_order'] = [name if item == previous else item
                for item in self.state.get('category_order', []) if not (delete and item == previous)]
            if self.state.get('primary_category') == previous:
                self.state['primary_category'] = None if delete else name
            icons = self.state.get('category_icons', {})
            icon = icons.pop(previous, None)
            source = self.state.get('category_icon_sources', {}).pop(previous, None)
            if source is not None and not delete:
                self.state['category_icon_sources'][name] = source
            if icon is not None and not delete:
                icons[name] = icon
        self.state['categories'] = sorted(names, key=str.casefold)
        self.save()

    def category_icon(self, name):
        filename = self.state.get('category_icons', {}).get(name or '')
        if filename:
            path = self.root / 'category-icons' / Path(filename).name
            if path.is_file():
                return str(path)
        return ''

    def set_category_icon(self, name, source=None, credit=None):
        if name is not None and name not in self.categories():
            raise ValueError(tr('La categoría ya no existe.'))
        if source is None:
            self.state.setdefault('category_icons', {}).pop(name or '', None)
        else:
            path = SteamGridDB('', self.root / 'category-icons').import_artwork(source)
            self.state.setdefault('category_icons', {})[name or ''] = Path(path).name
        if credit and source is not None:
            self.state.setdefault('category_icon_sources', {})[name or ''] = {
                key: credit.get(key, '') for key in ('source', 'author', 'license')}
        else:
            self.state.get('category_icon_sources', {}).pop(name or '', None)
        self.save()

    def primary_category(self):
        name = self.state.get('primary_category')
        return name if name in self.categories() else None

    def set_primary_category(self, name):
        if name is not None and name not in self.categories():
            raise ValueError(tr('La categoría ya no existe.'))
        self.state['primary_category'] = name
        self.save()

    def move_category(self, name, step):
        names = self.categories()
        if name not in names:
            raise ValueError(tr('La categoría ya no existe.'))
        index = names.index(name)
        destination = max(0, min(len(names) - 1, index + step))
        names.insert(destination, names.pop(index))
        self.state['category_order'] = names
        self.save()

    def set_category_games(self, name, identities):
        if name not in self.categories():
            raise ValueError(tr('La categoría ya no existe.'))
        games = self.games()
        selected = set(identities)
        if selected - {game['id'] for game in games}:
            raise ValueError(tr('El juego ya no existe.'))
        for game in games:
            categories = [item for item in game.get('categories', []) if item != name]
            if game['id'] in selected:
                categories.append(name)
            if game['kind'] in ('faugus', 'steam', 'heroic'):
                self.state['overrides'].setdefault(game['id'], {})['categories'] = categories
            else:
                next(row for row in self.state['games'] if row['id'] == game['id'])['categories'] = categories
        self.save()

    def remove(self, game):
        if game['kind'] in ('faugus', 'steam', 'heroic'):
            self.state['excluded_imports'] = sorted(set(self.state.get('excluded_imports', [])) | {game['id']})
        else:
            self.state['games'] = [g for g in self.state['games'] if g['id'] != game['id']]
        self.save()

    def restore_excluded_imports(self):
        count = len(self.state.get('excluded_imports', []))
        self.state['excluded_imports'] = []
        self.save()
        return count

    def record_session(self, game, seconds, started, exit_code):
        activity = self.state.setdefault('activity', {}).setdefault(game['id'], {})
        seconds = max(0, int(seconds))
        activity['sessions'] = activity.get('sessions', 0) + 1
        activity['seconds'] = activity.get('seconds', 0) + seconds
        activity['last_played'] = started
        activity['last_seconds'] = seconds
        history = activity.setdefault('history', [])
        history.insert(0, {'started': started, 'seconds': seconds, 'exit_code': exit_code})
        del history[8:]
        self.save()

    def game_stats(self, game):
        activity = self.state.get('activity', {}).get(game['id'], {})
        # Faugus already measures its own playtime; never add the same session twice.
        seconds = game.get('playtime', 0) if game['kind'] == 'faugus' else activity.get('seconds', 0)
        return {'seconds': max(0, int(seconds or 0)),
                'sessions': activity.get('sessions', 0),
                'last_played': max(str(game.get('last_played') or ''), str(activity.get('last_played') or '')),
                'last_seconds': activity.get('last_seconds'),
                'history': activity.get('history', [])}

    @staticmethod
    def local_game(title, path, arguments='', cwd='', identity=None, cover=''):
        target = Path(path).expanduser().resolve()
        if not title.strip():
            raise ValueError(tr('Escribe un nombre para el juego.'))
        if not target.is_file() or target.suffix.lower() not in ('.sh', '.appimage'):
            raise ValueError(tr('Selecciona un archivo .sh o .AppImage existente.'))
        shlex.split(arguments)  # Report unbalanced quotes before saving.
        working = Path(cwd).expanduser().resolve() if cwd.strip() else target.parent
        if not working.is_dir():
            raise ValueError(tr('El directorio de trabajo no existe.'))
        return dict(id=identity or str(uuid.uuid4()), title=title.strip(), kind='local',
                    path=str(target), arguments=arguments, cwd=str(working), cover=cover)


def launch_command(game):
    if game['kind'] == 'heroic':
        url = launch_url(game)
        if game.get('install') == 'flatpak':
            if not shutil.which('flatpak'):
                raise ValueError(tr('No se encuentra Flatpak.'))
            return ['flatpak', 'run', 'com.heroicgameslauncher.hgl', '--no-gui', url], None
        executable = shutil.which('heroic')
        if not executable:
            raise ValueError(tr('No se encuentra Heroic Games Launcher.'))
        return [executable, '--no-gui', url], None
    if game['kind'] == 'steam':
        appid = str(game.get('steam_appid', ''))
        if not appid.isdigit() or int(appid) <= 0:
            raise ValueError(tr('Identificador de Steam no válido.'))
        arguments = ['-silent', '-applaunch', appid]
        if game.get('install') == 'flatpak':
            if not shutil.which('flatpak'):
                raise ValueError(tr('No se encuentra Flatpak.'))
            return ['flatpak', 'run', 'com.valvesoftware.Steam', *arguments], None
        executable = shutil.which('steam')
        if not executable:
            raise ValueError(tr('No se encuentra Steam.'))
        return [executable, *arguments], None
    if game['kind'] == 'faugus':
        if game['install'] == 'flatpak':
            if not shutil.which('flatpak'):
                raise ValueError(tr('No se encuentra Flatpak.'))
            return ['flatpak', 'run', 'io.github.Faugus.faugus-launcher', '--game', str(game['gameid'])], None
        launcher = shutil.which('faugus-launcher')
        if not launcher:
            raise ValueError(tr('No se encuentra faugus-launcher.'))
        return [launcher, '--game', str(game['gameid'])], None
    path = Path(game['path'])
    if not path.is_file():
        raise ValueError(tr('El archivo del juego ya no existe.'))
    if path.suffix.lower() == '.sh':
        command = ['bash', str(path)]
    else:
        if not os.access(path, os.X_OK):
            raise ValueError(tr('La AppImage necesita permiso de ejecución. Actívalo en las propiedades del archivo.'))
        command = [str(path)]
    return command + shlex.split(game.get('arguments', '')), game.get('cwd') or str(path.parent)


def launch(game, log_dir):
    command, cwd = launch_command(game)
    env = dict(os.environ)
    token = uuid.uuid4().hex
    if os.environ.get('ESTANTE_APPDIR'):
        env = dict(os.environ)
        for name in ('PYTHONHOME', 'PYTHONPATH', 'GI_TYPELIB_PATH', 'GIO_MODULE_DIR',
                     'GSETTINGS_SCHEMA_DIR', 'XDG_DATA_DIRS', 'FONTCONFIG_FILE', 'SSL_CERT_FILE',
                     'GDK_PIXBUF_MODULE_FILE', 'GDK_PIXBUF_MODULEDIR', 'GLYCIN_DATA_DIR', 'PATH',
                     'QT_PLUGIN_PATH', 'QML_IMPORT_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            marker = 'ESTANTE_HOST_' + name
            if marker not in env:
                continue
            original = env.pop(marker)
            if original:
                env[name] = original
            else:
                env.pop(name, None)
        env.pop('ESTANTE_APPDIR', None)
    env['ESTANTE_GAME_SESSION'] = token
    if command[:2] == ['flatpak', 'run']:
        command.insert(2, '--env=ESTANTE_GAME_SESSION=' + token)
    with (Path(log_dir) / 'launch.log').open('w') as log:
        process = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log, start_new_session=True, env=env)
    process.estante_session_token = token
    return process


class SteamGridDB:
    def __init__(self, key, cache):
        self.key, self.cache = key.strip(), Path(cache)

    def api(self, route):
        if not self.key:
            raise ValueError(tr('Añade tu clave de SteamGridDB en Preferencias.'))
        request = Request('https://www.steamgriddb.com/api/v2/' + route,
                          headers={'Authorization': 'Bearer ' + self.key, 'User-Agent': 'Estante/0.1'})
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        if not result.get('success'):
            raise ValueError(tr('SteamGridDB no pudo completar la búsqueda.'))
        return result['data']

    def search(self, title):
        return self.api('search/autocomplete/' + quote(title, safe=''))

    def grids(self, game_id, square=False):
        dimensions = '512x512,1024x1024' if square else '600x900'
        return self.api(f'grids/game/{int(game_id)}?dimensions={dimensions}&types=static')

    def logos(self, game_id):
        return self.api(f'logos/game/{int(game_id)}?types=static')

    def logo(self, game):
        game_id = self.resolve_game_id(game)
        if not game_id:
            return None
        images = self.logos(game_id)
        if not images:
            return None
        return {'logo': self.download(images[0]['url']), 'steamgriddb_id': game_id}

    def heroes(self, game_id):
        return self.api(f'heroes/game/{int(game_id)}?types=static')

    def resolve_game_id(self, game):
        game_id = game.get('steamgriddb_id')
        if not game_id:
            def normalized(title):
                return ''.join(c for c in title.casefold() if c.isalnum())
            matches = [row for row in self.search(game['title'])
                       if normalized(row['name']) == normalized(game['title'])]
            if len(matches) != 1:
                return None
            game_id = matches[0]['id']
        return game_id

    def square_cover(self, game):
        game_id = self.resolve_game_id(game)
        if not game_id:
            return None
        grids = self.grids(game_id, square=True)
        if not grids:
            return None
        return {'square_cover': self.download(grids[0]['url']), 'steamgriddb_id': game_id}

    def banner(self, game):
        game_id = self.resolve_game_id(game)
        if not game_id:
            return None
        heroes = self.heroes(game_id)
        if not heroes:
            return None
        return {'banner': self.download(heroes[0]['url']), 'steamgriddb_id': game_id}

    def import_artwork(self, path):
        import hashlib
        self.cache.mkdir(parents=True, exist_ok=True)
        with Path(path).expanduser().open('rb') as source:
            return self.store_artwork(source, hashlib.sha256())

    def store_artwork(self, source, digest=None, target=None):
        """Stream to a private temporary file; publish only a complete transfer."""
        fd, name = tempfile.mkstemp(prefix='.artwork-', dir=self.cache)
        try:
            with os.fdopen(fd, 'wb') as output:
                while chunk := source.read(256 * 1024):
                    output.write(chunk)
                    if digest is not None:
                        digest.update(chunk)
            if target is None:
                target = self.cache / (digest.hexdigest() + '.img')
            os.replace(name, target)
            return str(target)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def validate_artwork_url(url, custom=False):
        parsed = urlparse(url)
        if not parsed.hostname or parsed.scheme not in ('http', 'https') or (not custom and
                (parsed.scheme != 'https' or not (parsed.hostname == 'steamgriddb.com' or
                 (parsed.hostname or '').endswith('.steamgriddb.com')))):
            raise ValueError(tr('Dirección de carátula no válida.'))

    def artwork_size(self, url):
        self.validate_artwork_url(url)
        import hashlib
        cached = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.img')
        if cached.is_file():
            return cached.stat().st_size
        try:
            request = Request(url, method='HEAD', headers={'User-Agent': 'Estante/0.1'})
            with urlopen(request, timeout=10) as response:
                size = int(response.headers.get('Content-Length', 0))
                return size if size > 0 else None
        except (OSError, ValueError):
            return None

    def download(self, url, custom=False):
        self.validate_artwork_url(url, custom)
        import hashlib
        self.cache.mkdir(parents=True, exist_ok=True)
        target = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.img')
        if not target.exists():
            with urlopen(Request(url, headers={'User-Agent': 'Estante/0.1'}), timeout=20) as response:
                self.store_artwork(response, target=target)
        return str(target)
