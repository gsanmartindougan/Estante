"""Read RecompLauncher's installed library without changing its files."""
import json
from pathlib import Path


APP_ID = 'com.recomplauncher.app'


def discover_recomp(home, data):
    home, data = Path(home), Path(data)
    roots = [(data / APP_ID, 'native'),
             (home / '.var/app' / APP_ID / 'data' / APP_ID, 'flatpak')]
    games = {}
    for root, install in roots:
        try:
            library = json.loads((root / 'library.json').read_text())
        except (OSError, ValueError):
            continue
        installed = library.get('installed', {}) if isinstance(library, dict) else {}
        if not isinstance(installed, dict):
            continue
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
            title = entry.get('game') or entry.get('name') or game_id
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
