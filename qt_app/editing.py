"""Compatible, field-scoped edits shared by the Qt editor and its tests."""
from datetime import datetime
from library import Library

TEXT_FIELDS = ('title', 'description', 'synopsis', 'release_date')
LIST_FIELDS = ('developers', 'publishers', 'genres', 'platforms')


def draft_for(game):
    metadata = game.get('metadata') or {}
    return {**{field: str(metadata.get(field) or (game['title'] if field == 'title' else '')) for field in TEXT_FIELDS},
            **{field: ', '.join(metadata.get(field) or []) for field in LIST_FIELDS},
            'categories': ', '.join(game.get('categories') or [])}


def clean_draft(values, validate=True):
    result = {field: str(values.get(field) or '').strip() for field in TEXT_FIELDS}
    for field in (*LIST_FIELDS, 'categories'):
        result[field] = list(dict.fromkeys(value.strip() for value in str(values.get(field) or '').split(',') if value.strip()))
    date = result['release_date']
    if date:
        for pattern in ('%Y-%m-%d', '%d/%m/%Y'):
            try:
                result['release_date'] = datetime.strptime(date, pattern).strftime('%Y-%m-%d')
                break
            except ValueError:
                continue
        else:
            if validate:
                raise ValueError('Introduce una fecha válida: DD/MM/AAAA o AAAA-MM-DD.')
    if validate and any(name.casefold() in ('todos', 'all') for name in result['categories']):
        raise ValueError('Todos es un filtro; utiliza otro nombre de categoría.')
    return result


def save_draft(root, identity, original, values):
    before, edited = clean_draft(original, validate=False), clean_draft(values)
    changes = {field: value for field, value in edited.items() if value != before[field]}
    library = Library(data_dir=root)
    current = next((game for game in library.games() if game['id'] == identity), None)
    if current is None:
        raise ValueError('El juego ya no está en la biblioteca.')
    latest = clean_draft(draft_for(current), validate=False)
    for field in changes:
        if latest[field] != before[field] and latest[field] != edited[field]:
            raise ValueError('Este campo cambió mientras editabas: ' + field + '. Cierra y vuelve a abrir la ficha.')
    if changes:
        updated = dict(current)
        metadata = dict(current.get('metadata') or {})
        for field, value in changes.items():
            if field == 'categories':
                updated[field] = value
            else:
                metadata[field] = value
                metadata['manually_edited'] = True
        updated['metadata'] = metadata
        library.put(updated)
    return library.games()
