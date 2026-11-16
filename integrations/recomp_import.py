"""Read RecompLauncher's installed library without changing its files."""
import json
from pathlib import Path


DATA_ID = 'com.recomplauncher.app'
FLATPAK_ID = 'com.recomplauncher.RecompLauncher'


def discover_recomp(home, data):
    home, data = Path(home), Path(data)
    roots = [(data / DATA_ID, 'native'),
             (home / '.var/app' / FLATPAK_ID / 'data' / DATA_ID, 'flatpak')]
    games = {}
    for root, install in roots:
        try:
            library = json.loads((root / 'library.json').read_text())
        except (OSError, ValueError):
            continue
        installed = library.get('installed', {}) if isinstance(library, dict) else {}
        if not isinstance(installed, dict):
            continue
        try:
            catalog = json.loads((root / 'cache/pc-catalog.json').read_text())
        except (OSError, ValueError):
            catalog = {}
        catalog_apps = catalog.get('apps', []) if isinstance(catalog, dict) else []
        catalog_names = {row.get('id'): row.get('game') for row in catalog_apps
                         if isinstance(row, dict) and isinstance(row.get('id'), str)
                         and isinstance(row.get('game'), str) and row.get('game')}
        for game_id, entry in installed.items():
            if not isinstance(game_id, str) or not game_id or '\0' in game_id or not isinstance(entry, dict):
                continue
            raw_directory = entry.get('path')
            if not isinstance(raw_directory, str) or not raw_directory:
                continue
            directory = Path(raw_directory).expanduser()
            if not directory.is_absolute() or not directory.is_dir():
                continue
            identity = 'recomp:' + game_id
            if identity in games:
                continue
            title = entry.get('game') or catalog_names.get(game_id) or entry.get('name') or game_id
            cover = Path(str(entry.get('cover_file') or '')).expanduser()
            if not cover.is_absolute():
                cover = root / cover
            games[identity] = {
                'id': identity,
                'kind': 'recomp',
                'recomp_id': game_id,
                'install': install,
                'title': str(title),
                'path': str(directory),
                'cover': str(cover) if cover.is_file() else '',
            }
    return sorted(games.values(), key=lambda game: game['title'].casefold())
