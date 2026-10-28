"""Read Heroic's installed manifests; never modify its configuration or credentials."""
import json
from pathlib import Path
from urllib.parse import unquote, urlparse, urlencode

RUNNERS = ('legendary', 'gog', 'nile', 'sideload')


def read(path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def rows(value, key=None):
    if key and isinstance(value, dict):
        value = value.get(key, [])
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [dict(row, app_name=row.get('app_name', name)) for name, row in value.items() if isinstance(row, dict)]
    return []


def launch_url(game):
    runner, name = game.get('heroic_runner'), game.get('heroic_app_name')
    if runner not in RUNNERS or not isinstance(name, str) or not name or '\0' in name:
        raise ValueError('Identificador de Heroic no válido.')
    return 'heroic://launch?' + urlencode({'appName': name, 'runner': runner, 'gui': 'false'})


def local_art(value, root):
    if not isinstance(value, str) or not value:
        return ''
    if value.startswith('file://'):
        value = unquote(urlparse(value).path)
    elif '://' in value:
        return ''
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return str(path) if path.is_file() else ''


def discover_heroic(home, config):
    home, config = Path(home), Path(config)
    roots = [(config / 'heroic', 'native'),
             (home / '.var/app/com.heroicgameslauncher.hgl/config/heroic', 'flatpak')]
    games = {}
    for root, install in roots:
        if not root.is_dir():
            continue
        caches = {}
        for runner, filename, key in [('gog', 'gog_library', 'games'), ('nile', 'nile_library', 'library')]:
            caches[runner] = {str(row.get('app_name')): row for row in rows(read(root/'store_cache'/f'{filename}.json', {}), key)}
        # Older Heroic versions used the global Legendary directory.
        epic = root/'legendaryConfig/legendary'
        if not (epic/'installed.json').is_file():
            epic = root.parent/'legendary'
        manifests = [('legendary', rows(read(epic/'installed.json', {}))),
                     ('gog', rows(read(root/'gog_store/installed.json', {}), 'installed')),
                     ('nile', rows(read(root/'nile_config/nile/installed.json', []))),
                     ('sideload', rows(read(root/'sideload_apps/library.json', {}), 'games'))]
        # Nile's own library contains titles even if Heroic's UI cache is missing.
        amazon = {}
        for row in rows(read(root/'nile_config/nile/library.json', [])):
            product = row.get('product', {})
            if isinstance(product, dict) and product.get('id'):
                amazon[str(product['id'])] = product
        for runner, installed in manifests:
            for entry in installed:
                name = entry.get('app_name') if runner == 'legendary' else (entry.get('appName') or (entry.get('manifest') or {}).get('app_name')) if runner == 'gog' else entry.get('id') if runner == 'nile' else entry.get('app_name')
                if not isinstance(name, (str, int)) or not str(name) or '\0' in str(name):
                    continue
                name = str(name)
                metadata = caches.get(runner, {}).get(name, {})
                if runner == 'legendary' and Path(name).name == name:
                    epic_metadata = read(epic/'metadata'/f'{name}.json', {})
                    metadata = {'title': epic_metadata.get('app_title')}
                    images = epic_metadata.get('metadata', {}).get('keyImages', [])
                    for image in images:
                        field = {'DieselGameBoxTall': 'art_cover', 'OfferImageTall': 'art_cover',
                                 'DieselGameBox': 'art_square', 'OfferImageWide': 'art_background'}.get(image.get('type'))
                        if field and image.get('url'): metadata[field] = image['url']
                elif runner == 'nile' and not metadata:
                    product = amazon.get(name, {})
                    detail = product.get('productDetail', {})
                    info = detail.get('details', {})
                    metadata = dict(title=product.get('title'), art_cover=info.get('backgroundUrl2') or detail.get('iconUrl'),
                                    art_background=info.get('backgroundUrl1'), art_square=detail.get('iconUrl'), art_logo=info.get('logoUrl'))
                if runner == 'sideload':
                    metadata = entry
                detail = entry.get('install', {}) if runner == 'sideload' else entry
                if not isinstance(detail, dict) or detail.get('is_dlc') or metadata.get('is_dlc') or entry.get('is_installed') is False:
                    continue
                directory = detail.get('path') if runner == 'nile' else detail.get('install_path')
                executable = detail.get('executable', '')
                if not directory and runner == 'sideload' and executable:
                    directory = str(Path(executable).parent)
                if not isinstance(directory, str) or not directory or not Path(directory).expanduser().is_dir():
                    continue
                directory = Path(directory).expanduser()
                if runner == 'sideload' and not (directory / executable).is_file():
                    continue
                identity = f'heroic:{runner}:{name}'
                if identity in games:
                    continue
                title = entry.get('title') or metadata.get('title') or amazon.get(name, {}).get('title')
                game = dict(id=identity, kind='heroic', install=install, heroic_app_name=name,
                            heroic_runner=runner, title=str(title or name), path=str(directory), cover='')
                if isinstance(executable, str) and executable:
                    game['executable'] = str(directory / executable.replace('\\', '/'))
                remote = {}
                for field, art in [('cover','art_cover'), ('square_cover','art_square'), ('banner','art_background'), ('logo','art_logo')]:
                    value = metadata.get(art, '')
                    local = local_art(value, root)
                    if local:
                        game[field] = local
                    elif isinstance(value, str) and value.startswith('https://'):
                        remote[field] = value
                if remote:
                    game['heroic_artwork'] = remote
                games[identity] = game
    return sorted(games.values(), key=lambda game: game['title'].casefold())
