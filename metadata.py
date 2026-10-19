"""Optional, keyless Wikidata game descriptions; matches are reviewed in the UI."""
from i18n import tr
from i18n import get_language
import json
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class GameMetadata:
    GAME_TYPES = {'Q7889', 'Q60997816', 'Q96240590', 'Q209163', 'Q1066707'}

    def __init__(self, cache):
        self.cache = Path(cache)
        self.language = get_language()
        self.class_parents = {}

    @staticmethod
    def references(entity, property_id):
        return {row['mainsnak']['datavalue']['value']['id']
                for row in entity.get('claims', {}).get(property_id, [])
                if row.get('rank') != 'deprecated' and
                isinstance(row.get('mainsnak', {}).get('datavalue', {}).get('value'), dict) and
                'id' in row['mainsnak']['datavalue']['value']}

    def api(self, **params):
        query = urlencode({'format': 'json', **params})
        request = Request('https://www.wikidata.org/w/api.php?' + query,
                          headers={'User-Agent': 'Estante/0.1 (Linux game library; Wikidata metadata)',
                                   'Accept': 'application/json'})
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
        if 'error' in result:
            raise ValueError(result['error'].get('info', tr('No se pudo consultar Wikidata.')))
        return result

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
