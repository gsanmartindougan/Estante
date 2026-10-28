"""Optional, keyless Wikidata game descriptions; matches are reviewed in the UI."""
from i18n import tr
from i18n import get_language
import json
from pathlib import Path
import re
import time
import threading
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from version import __version__
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MetadataRateLimitError(ValueError):
    """The metadata provider exhausted its retry allowance."""


class GameMetadata:
    GAME_TYPES = {'Q7889', 'Q60997816', 'Q96240590', 'Q209163', 'Q1066707'}

    _request_lock = threading.Lock()
    _next_request_at = 0.0
    REQUEST_INTERVAL = 1.1
    MAX_ATTEMPTS = 4

    def __init__(self, cache, on_wait=None):
        self.cache = Path(cache)
        self.language = get_language()
        self.class_parents = {}
        self.on_wait = on_wait

    @staticmethod
    def references(entity, property_id):
        return {row['mainsnak']['datavalue']['value']['id']
                for row in entity.get('claims', {}).get(property_id, [])
                if row.get('rank') != 'deprecated' and
                isinstance(row.get('mainsnak', {}).get('datavalue', {}).get('value'), dict) and
                'id' in row['mainsnak']['datavalue']['value']}

    @staticmethod
    def retry_delay(value, attempt):
        fallback = 5 * 2 ** attempt
        if value:
            try:
                return max(fallback, float(value))
            except (ValueError, TypeError):
                try:
                    return max(fallback, parsedate_to_datetime(value).timestamp() - time.time())
                except (ValueError, TypeError, OverflowError):
                    pass
        return fallback

    def api(self, **params):
        query = urlencode({'format': 'json', 'maxlag': 5, **params})
        request = Request('https://www.wikidata.org/w/api.php?' + query,
                          headers={'User-Agent': f'Estante/{__version__} (https://github.com/gsanmartindougan/Estante; Linux game library)',
                                   'Accept': 'application/json'})
        # All clients share the same gate, including manual metadata pickers.
        with GameMetadata._request_lock:
            for attempt in range(self.MAX_ATTEMPTS):
                delay = max(0, GameMetadata._next_request_at - time.monotonic())
                if delay:
                    if self.on_wait and delay >= 2:
                        self.on_wait(delay)
                    time.sleep(delay)
                GameMetadata._next_request_at = time.monotonic() + self.REQUEST_INTERVAL
                retry_after = None
                try:
                    with urlopen(request, timeout=20) as response:
                        result = json.load(response)
                        retry_after = response.headers.get('Retry-After')
                except HTTPError as error:
                    if error.code not in (429, 503):
                        raise
                    retry_after = error.headers.get('Retry-After') if error.headers else None
                    error.close()
                else:
                    error = result.get('error')
                    if not error:
                        return result
                    if error.get('code') not in ('maxlag', 'ratelimited'):
                        raise ValueError(error.get('info', tr('No se pudo consultar Wikidata.')))
                delay = self.retry_delay(retry_after, attempt)
                GameMetadata._next_request_at = time.monotonic() + delay
                if attempt == self.MAX_ATTEMPTS - 1:
                    raise MetadataRateLimitError(tr('Wikidata sigue limitando las consultas. Vuelve a intentarlo más tarde con «Completar datos faltantes».'))

    def search(self, title):
        result = self.api(action='wbsearchentities', search=title, language='en', uselang=self.language,
                          type='item', limit=20)
        rows = result.get('search', [])
        if not rows:
            return []
        entities = self.api(action='wbgetentities', ids='|'.join(row['id'] for row in rows), props='claims')['entities']
        types = {row['id']: self.references(entities.get(row['id'], {}), 'P31') for row in rows}
        frontier = set().union(*types.values()) - self.GAME_TYPES
        for _ in range(4):
            pending = frontier - self.class_parents.keys() - self.GAME_TYPES
            if pending:
                ids = sorted(pending)
                for start in range(0, len(ids), 50):
                    batch = ids[start:start+50]
                    classes = self.api(action='wbgetentities', ids='|'.join(batch), props='claims')['entities']
                    for identity in batch:
                        self.class_parents[identity] = self.references(classes.get(identity, {}), 'P279')
            frontier = set().union(*(self.class_parents.get(identity, set()) for identity in frontier)) - self.GAME_TYPES
            if not frontier:
                break

        def is_game_type(identity, visited=None):
            if identity in self.GAME_TYPES:
                return True
            visited = set() if visited is None else visited
            if identity in visited:
                return False
            visited.add(identity)
            return any(is_game_type(parent, visited) for parent in self.class_parents.get(identity, set()))

        return [{'id': row['id'], 'name': row.get('label', row['id']),
                 'description': row.get('description', '')} for row in rows
                if any(is_game_type(identity) for identity in types[row['id']])][:10]

    def fetch(self, entity_id):
        if not re.fullmatch(r'Q[1-9][0-9]*', entity_id):
            raise ValueError(tr('Identificador de Wikidata no válido.'))
        file = self.cache / (entity_id + '.' + self.language + '.json')
        if file.is_file():
            return json.loads(file.read_text())
        entities = self.api(action='wbgetentities', ids=entity_id, props='labels|descriptions|claims',
                            languages=self.language + '|en|es', languagefallback=1)['entities']
        entity = entities[entity_id]
        claims = entity.get('claims', {})

        def values(prop):
            return [row['mainsnak']['datavalue']['value'] for row in claims.get(prop, [])
                    if row.get('rank') != 'deprecated' and 'datavalue' in row.get('mainsnak', {})]

        properties = {'developers': 'P178', 'publishers': 'P123', 'genres': 'P136', 'platforms': 'P400'}
        references = {field: [value['id'] for value in values(prop) if isinstance(value, dict) and 'id' in value]
                      for field, prop in properties.items()}
        ids = list(dict.fromkeys(identity for rows in references.values() for identity in rows))
        labels = {}
        for start in range(0, len(ids), 50):
            labels.update(self.api(action='wbgetentities', ids='|'.join(ids[start:start+50]),
                props='labels', languages=self.language + '|en|es', languagefallback=1)['entities'])

        def text(row, field):
            choices = row.get(field, {})
            return (choices.get(self.language) or choices.get('en') or choices.get('es') or {}).get('value', '')

        result = {field: list(dict.fromkeys(text(labels.get(identity, {}), 'labels') or identity
                                            for identity in identities))
                  for field, identities in references.items()}
        dates = sorted((value['time'].lstrip('+').split('T')[0], value.get('precision', 11))
                       for value in values('P577') if isinstance(value, dict) and value.get('time'))
        date, precision = dates[0] if dates else ('', 11)
        if precision < 11:
            date = date[:7] if precision == 10 else date[:4]
        result.update(title=text(entity, 'labels'), description=text(entity, 'descriptions'),
                      release_date=date, source='https://www.wikidata.org/wiki/' + entity_id,
                      entity_id=entity_id)
        self.cache.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        return result


class CategoryIcons:
    """Search the Bootstrap Icons catalogue and cache small, standalone PNGs."""
    CATALOG_URL = 'https://raw.githubusercontent.com/twbs/icons/main/font/bootstrap-icons.json'
    ICON_ROOT = 'https://raw.githubusercontent.com/twbs/icons/main/icons/'
    NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')

    def __init__(self, cache):
        self.cache = Path(cache)
        self.names = None

    @staticmethod
    def request(url):
        return urlopen(Request(url, headers={
            'User-Agent': f'Estante/{__version__} (https://github.com/gsanmartindougan/Estante)'}), timeout=20)

    @classmethod
    def catalog_names(cls, data):
        names = data.keys() if isinstance(data, dict) else data if isinstance(data, list) else []
        return sorted({name for name in names if isinstance(name, str) and cls.NAME.fullmatch(name)})

    def catalog(self):
        if self.names is not None:
            return self.names
        cached = self.cache / 'bootstrap-catalog.json'
        previous = []
        try:
            previous = self.catalog_names(json.loads(cached.read_text()))
            if previous and time.time() - cached.stat().st_mtime < 86400:
                self.names = previous
                return self.names
        except (OSError, ValueError):
            pass
        try:
            with self.request(self.CATALOG_URL) as response:
                names = self.catalog_names(json.load(response))
            if not names:
                raise ValueError(tr('No se pudo cargar el catálogo de Bootstrap Icons.'))
        except (OSError, ValueError):
            if not previous:
                raise
            names = previous
        self.names = names
        try:
            import os
            import tempfile
            self.cache.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', dir=self.cache, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(names, stream)
            try:
                os.replace(temporary, cached)
            finally:
                temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return names

    def search(self, query):
        terms = query.strip().casefold().replace('_', '-').split()
        return [{'name': name, 'url': self.ICON_ROOT + name + '.svg',
                 'source': 'https://icons.getbootstrap.com/icons/' + name + '/',
                 'author': 'The Bootstrap Authors', 'license': 'MIT'}
                for name in self.catalog() if all(term in name for term in terms)]

    @staticmethod
    def render_svg(data, target):
        import cairo
        import gi
        gi.require_version('Rsvg', '2.0')
        from gi.repository import Rsvg
        # Render directly, without Glycin or an external codec process.
        handle = Rsvg.Handle.new_from_data(data.replace(b'currentColor', b'#ffffff'))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 128, 128)
        viewport = Rsvg.Rectangle()
        viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, 128, 128
        handle.render_document(cairo.Context(surface), viewport)
        surface.write_to_png(str(target))

    @classmethod
    def validate_download_url(cls, url):
        if not url.startswith(cls.ICON_ROOT) or not url.endswith('.svg'):
            raise ValueError(tr('Dirección de icono no válida.'))
        if not cls.NAME.fullmatch(url[len(cls.ICON_ROOT):-4]):
            raise ValueError(tr('Dirección de icono no válida.'))

    def icon_path(self, url):
        import hashlib
        return self.cache / ('icon-' + hashlib.sha256(url.encode()).hexdigest() + '.png')

    def download(self, url):
        import os
        import tempfile
        self.validate_download_url(url)
        self.cache.mkdir(parents=True, exist_ok=True)
        target = self.icon_path(url)
        if not target.exists():
            with self.request(url) as response:
                data = response.read()
            with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as stream:
                temporary = Path(stream.name)
            try:
                self.render_svg(data, temporary)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return str(target)


class IconifyIcons(CategoryIcons):
    ICON_ROOT = 'https://api.iconify.design/'

    def __init__(self, cache):
        super().__init__(cache)
        self.searches = {}
        self.on_wait = None

    _request_lock = threading.Lock()
    _cache_lock = threading.Lock()
    _next_request_at = 0.0
    REQUEST_INTERVAL = 0.5
    MAX_ATTEMPTS = 3
    MAX_WAIT = 30

    def request(self, url):
        cls = IconifyIcons
        with cls._request_lock:
            for attempt in range(self.MAX_ATTEMPTS):
                delay = max(0, cls._next_request_at - time.monotonic())
                if delay > self.MAX_WAIT:
                    raise ValueError(tr('Iconify solicita una pausa de {seconds} s. Prueba más tarde.').format(seconds=round(delay)))
                if delay:
                    if self.on_wait and delay >= 1:
                        self.on_wait(delay)
                    time.sleep(delay)
                cls._next_request_at = time.monotonic() + self.REQUEST_INTERVAL
                try:
                    return CategoryIcons.request(url)
                except HTTPError as error:
                    if error.code not in (429, 503):
                        error.close()
                        raise
                    delay = GameMetadata.retry_delay(error.headers.get('Retry-After') if error.headers else None, attempt)
                    error.close()
                    cls._next_request_at = time.monotonic() + delay
                    if attempt == self.MAX_ATTEMPTS - 1:
                        raise ValueError(tr('Iconify solicita una pausa de {seconds} s. Prueba más tarde.').format(seconds=round(delay)))

    def json_request(self, url):
        import hashlib
        import os
        import tempfile
        with IconifyIcons._cache_lock:
            cached = self.cache / ('iconify-' + hashlib.sha256(url.encode()).hexdigest() + '.json')
            previous = None
            try:
                previous = json.loads(cached.read_text())
                if isinstance(previous, dict) and time.time() - cached.stat().st_mtime < 86400:
                    return previous
            except (OSError, ValueError):
                pass
            try:
                with self.request(url) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise ValueError(tr('Respuesta de Iconify no válida.'))
            except (OSError, ValueError):
                if isinstance(previous, dict):
                    return previous
                raise
            temporary = None
            try:
                self.cache.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='w', dir=self.cache, delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(result, stream)
                os.replace(temporary, cached)
            except OSError:
                pass
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            return result

    @staticmethod
    def icon_svg(data, name):
        icon = data.get('icons', {}).get(name)
        if not isinstance(icon, dict) or not isinstance(icon.get('body'), str):
            return None
        # Rare aliases/transformed icons keep using Iconify's canonical SVG endpoint.
        if icon.get('rotate') or icon.get('hFlip') or icon.get('vFlip'):
            return None
        bounds = [icon.get(key, data.get(key, default)) for key, default in
                  (('left', 0), ('top', 0), ('width', 16), ('height', 16))]
        import math
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in bounds):
            return None
        if bounds[2] <= 0 or bounds[3] <= 0:
            return None
        viewbox = ' '.join(str(value) for value in bounds)
        return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="' + viewbox +
                '" fill="currentColor">' + icon['body'] + '</svg>').encode()

    def prepare(self, rows, cancelled=lambda: False):
        import os
        import tempfile
        groups = {}
        for row in rows:
            self.validate_download_url(row['url'])
            if self.icon_path(row['url']).exists():
                continue
            prefix, name = row['name'].split(':', 1)
            if self.NAME.fullmatch(prefix) and self.NAME.fullmatch(name):
                groups.setdefault(prefix, {})[name] = row
        for prefix, names in groups.items():
            if cancelled():
                return
            url = self.ICON_ROOT + prefix + '.json?' + urlencode({'icons': ','.join(sorted(names))})
            data = self.json_request(url)
            for name, row in names.items():
                if cancelled():
                    return
                svg = self.icon_svg(data, name)
                if svg is None:
                    continue
                self.cache.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as stream:
                    temporary = Path(stream.name)
                try:
                    self.render_svg(svg, temporary)
                    os.replace(temporary, self.icon_path(row['url']))
                finally:
                    temporary.unlink(missing_ok=True)

    @classmethod
    def validate_download_url(cls, url):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.netloc != 'api.iconify.design' or
                not re.fullmatch(r'/[a-z0-9]+(?:-[a-z0-9]+)*/[a-z0-9]+(?:-[a-z0-9]+)*\.svg', parsed.path) or
                parsed.query != 'color=%23ffffff' or parsed.fragment):
            raise ValueError(tr('Dirección de icono no válida.'))

    def search(self, query, full=False):
        query = query.strip()
        if not query:
            return []
        key = query, full
        if key in self.searches:
            return self.searches[key]
        limit = 999 if full else 64
        url = self.ICON_ROOT + 'search?' + urlencode({'query': query, 'limit': limit})
        result = self.json_request(url)
        collections = result.get('collections', {})
        rows = []
        seen = set()
        for identity in result.get('icons', []):
            if not isinstance(identity, str) or identity in seen or identity.count(':') != 1:
                continue
            prefix, name = identity.split(':')
            if not self.NAME.fullmatch(prefix) or not self.NAME.fullmatch(name):
                continue
            seen.add(identity)
            info = collections.get(prefix, {})
            rows.append({'name': identity,
                         'url': self.ICON_ROOT + prefix + '/' + name + '.svg?color=%23ffffff',
                         'source': 'https://icon-sets.iconify.design/' + prefix + '/' + name + '/',
                         'author': info.get('author', {}).get('name', ''),
                         'license': info.get('license', {}).get('spdx') or info.get('license', {}).get('title', '')})
        # Keep a few searches, never the entire remote catalogue.
        if len(self.searches) >= 8:
            self.searches.pop(next(iter(self.searches)))
        self.searches[key] = rows
        return rows
