"""Build synthetic library entries with independent artwork paths for stress tests."""
from copy import deepcopy
from pathlib import Path
import shutil
import tempfile


def populate_test_games(library, count):
    originals = library.games()
    if count < 1 or not originals:
        raise ValueError('The test needs a positive count and at least one source game.')
    artwork = Path(tempfile.mkdtemp(prefix='stress-artwork-', dir=library.root))
    games = []
    for index in range(count):
        game = deepcopy(originals[index % len(originals)])
        game.update(id=f'stress:{index:04d}', title=f'{index + 1:03d} · {game["title"]}',
                    kind='custom', path=shutil.which('true') or '/usr/bin/true',
                    arguments='', cwd=str(library.root), categories=[])
        for field in ('cover', 'square_cover', 'logo', 'banner', 'banner_secondary'):
            source = Path(game.get(field) or '')
            if source.is_file():
                target = artwork / f'{index:04d}-{field}{source.suffix}'
                shutil.copyfile(source, target)
                game[field] = str(target)
        games.append(game)
    library.state = {'games': games, 'overrides': {}, 'faugus': [], 'steam': [],
                     'source_categories_initialized': True, 'categories': []}
    library.save()
    return games
