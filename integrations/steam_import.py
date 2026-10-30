"""Read installed Steam games and local artwork without modifying Steam files."""
from pathlib import Path
import re


def read_vdf(path):
    text = Path(path).read_text(encoding='utf-8-sig')
    tokens = re.findall(r'//[^\n]*|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', text)
    tokens = [token for token in tokens if not token.startswith('//')]
    index = 0
    def value(token):
        return re.sub(r'\\(["\\])', r'\1', token[1:-1]) if token.startswith('"') else token
    def block(nested=False):
        nonlocal index
        result = {}
        while index < len(tokens):
            key = tokens[index]
            index += 1
            if key == '}':
                if not nested:
                    raise ValueError('Unexpected VDF closing brace')
                return result
            if key == '{' or index >= len(tokens):
                raise ValueError('Invalid VDF key/value')
            token = tokens[index]
            index += 1
            if token == '}':
                raise ValueError('Missing VDF value')
            result[value(key).casefold()] = block(True) if token == '{' else value(token)
        if nested:
            raise ValueError('Unclosed VDF block')
        return result
    return block()


def is_faugus_steam(game):
    return (str(game.get('runner', '')).strip().casefold() == 'steam' or
            str(game.get('path', '')).strip().casefold().startswith('steam://'))


def steam_roots(home, data):
    home, data = Path(home), Path(data)
    flatpak = home / '.var/app/com.valvesoftware.Steam'
    candidates = [(data / 'Steam', 'native'), (home / '.steam/steam', 'native'),
                  (home / '.steam/root', 'native'), (home / '.steam/debian-installation', 'native'),
                  (flatpak / '.local/share/Steam', 'flatpak'), (flatpak / '.steam/steam', 'flatpak'),
                  (flatpak / '.steam/root', 'flatpak')]
    seen = set()
    for path, install in candidates:
        resolved = path.resolve()
        if resolved not in seen and resolved.is_dir():
            seen.add(resolved)
            yield resolved, install


def cached_artwork(root, appid):
    cache = root / 'appcache/librarycache'
    result = {}
    for field, name in (('cover', 'library_600x900'), ('banner', 'library_hero'), ('logo', 'logo')):
        candidates = [cache / f'{appid}_{name}{suffix}' for suffix in ('.jpg', '.png')]
        directory = cache / appid
        if directory.is_dir():
            candidates.extend(sorted(directory.rglob(name + '.*')))
        path = next((path for path in candidates if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg')), None)
        if path:
            result[field] = str(path)
    return result


def discover_steam(home, data):
    games = {}
    for root, install in steam_roots(home, data):
        libraries = [root]
        for registry in (root / 'steamapps/libraryfolders.vdf', root / 'config/libraryfolders.vdf'):
            if not registry.is_file():
                continue
            folders = read_vdf(registry).get('libraryfolders', {})
            for key, entry in folders.items():
                path = entry.get('path') if isinstance(entry, dict) else entry if key.isdigit() else None
                if path:
                    libraries.append(Path(path).expanduser())
        for folder in dict.fromkeys(path.resolve() for path in libraries):
            for manifest in sorted((folder / 'steamapps').glob('appmanifest_*.acf')):
                try:
                    row = read_vdf(manifest).get('appstate', {})
                    appid, title = str(row.get('appid', '')), row.get('name', '').strip()
                    if not appid.isdigit() or int(appid) <= 0 or not title:
                        continue
                    tool = title.casefold()
                    if tool.startswith(('proton ', 'steam linux runtime', 'steamworks common redistributables')):
                        continue
                    directory = (folder / 'steamapps/common' / row.get('installdir', '')).resolve()
                    common = (folder / 'steamapps/common').resolve()
                    if not row.get('installdir') or not directory.is_relative_to(common) or not directory.is_dir():
                        continue
                    if not int(row.get('stateflags', '4')) & 4:
                        continue
                    game = dict(id=f'steam:{appid}', kind='steam', steam_appid=appid,
                                title=title, install=install, path=str(directory), cover='')
                    game.update(cached_artwork(root, appid))
                    games.setdefault(game['id'], game)
                except (ValueError, OSError, TypeError):
                    continue
    return sorted(games.values(), key=lambda game: game['title'].casefold())
