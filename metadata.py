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
                    raise ValueError(tr('Wikidata sigue limitando las consultas. Vuelve a intentarlo más tarde con «Completar datos faltantes».'))

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
