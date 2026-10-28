"""Explicit, non-destructive batch artwork and metadata scraping."""
from pathlib import Path

ARTWORK_FIELDS = ('cover', 'square_cover', 'logo', 'banner', 'banner_secondary')
METADATA_FIELDS = ('description', 'developers', 'publishers', 'genres', 'platforms', 'release_date')


def needs_artwork(game, field, replace=False):
    return replace or not Path(game.get(field) or '').is_file()


def scrape_game(game, artwork=None, metadata=None, replace=False, validate=None, fields=None):
    patch, errors = {}, []
    selected = set(ARTWORK_FIELDS if fields is None else fields)
    wanted = [field for field in ARTWORK_FIELDS if field in selected and needs_artwork(game, field, replace)]
    if artwork is not None and wanted:
        try:
            identity = artwork.resolve_game_id(game)
        except Exception as error:
            identity = None
            errors.append(str(error))
        if identity:
            sources = (
                (('cover',), lambda: artwork.grids(identity)),
                (('square_cover',), lambda: artwork.grids(identity, square=True)),
                (('logo',), lambda: artwork.logos(identity)),
                (('banner', 'banner_secondary'), lambda: artwork.heroes(identity)),
            )
            for fields, fetch in sources:
                if not any(field in wanted for field in fields):
                    continue
                try:
                    images = fetch()
                    for index, field in enumerate(fields):
                        if field not in wanted or index >= len(images):
                            continue
                        path = artwork.download(images[index]['url'])
                        if validate:
                            validate(path)
                        patch[field] = path
                except Exception as error:
                    errors.append(str(error))
            if patch:
                patch['steamgriddb_id'] = identity
    existing = game.get('metadata', {})
    if metadata is not None and (replace or any(not existing.get(field) for field in METADATA_FIELDS)):
        try:
            identity = existing.get('entity_id')
            if not identity:
                def normalized(value):
                    return ''.join(char for char in value.casefold() if char.isalnum())
                matches = [row for row in metadata.search(game['title'])
                           if normalized(row['name']) == normalized(game['title'])]
                identity = matches[0]['id'] if len(matches) == 1 else None
            if identity:
                result = metadata.fetch(identity)
                # Retain unavailable fields and preserve populated fields in fill mode.
                merged = dict(existing)
                for field, value in result.items():
                    if value and (replace or not merged.get(field)):
                        merged[field] = value
                if merged != existing:
                    patch['metadata'] = merged
        except Exception as error:
            errors.append(str(error))
    return patch, errors


def apply_scrape_patch(current, original, patch):
    """A later manual edit takes precedence over an in-flight scrape."""
    return {**current, **{field: value for field, value in patch.items()
                          if current.get(field) == original.get(field)}}


def apply_scrape_results(library, results):
    """Merge against current edits once, then persist the changed games together."""
    current_games = {game['id']: game for game in library.games()}
    updates, messages = [], []
    failures = 0
    for original, patch, errors in results:
        failures += len(errors)
        messages.extend(original['title'] + ': ' + error for error in errors[:max(0, 5-len(messages))])
        current = current_games.get(original['id'])
        if current is not None:
            updated = apply_scrape_patch(current, original, patch)
            if updated != current:
                current_games[original['id']] = updated
                updates.append(updated)
    library.put_many(updates)
    return len(updates), failures, messages
