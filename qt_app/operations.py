"""Qt-independent mutations using Estante's existing on-disk schema."""
import json
import os
from pathlib import Path
import tempfile
from library import Library

ARTWORK = ('cover', 'square_cover', 'logo', 'banner', 'banner_secondary')


def current_game(library, identity):
    game = next((row for row in library.games() if row['id'] == identity), None)
    if game is None:
        raise ValueError('El juego ya no está en la biblioteca.')
    return game


def update_game(root, identity, patch):
    library = Library(data_dir=root)
    current = current_game(library, identity)
    library.put({**current, **patch})
    return library.games()


def save_local(root, title, path, arguments='', cwd='', identity=None):
    library = Library(data_dir=root)
    previous = current_game(library, identity) if identity else {}
    if previous and previous['kind'] != 'local':
        raise ValueError('La ejecución de este juego se configura en Steam o Faugus.')
    game = Library.local_game(title, path, arguments, cwd, identity=identity, cover=previous.get('cover',''))
    library.put({**previous, **game})
    return game['id']


def save_settings(root, changes):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root/'settings.json'
    previous = json.loads(path.read_text()) if path.is_file() else {}
    result = {**previous, **changes}
    fd, temporary = tempfile.mkstemp(prefix='.settings-', dir=root)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return result
