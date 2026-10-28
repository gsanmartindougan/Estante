"""UI-independent catalog filtering and stable selection for the Qt frontend."""
import unicodedata


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold())
                   if not unicodedata.combining(c))


class Catalog:
    def __init__(self, games):
        self.games = list(games)
        self.visible = list(self.games)
        self.query = ''
        self.category = ''
        self.selected_id = self.visible[0]['id'] if self.visible else None
        self._reindex()

    @property
    def categories(self):
        return sorted({category for game in self.games for category in game.get('categories', [])},
                      key=str.casefold)

    @property
    def index(self):
        return self._indices.get(self.selected_id,-1)

    @property
    def selected(self):
        index = self.index
        return self.visible[index] if index >= 0 else None

    def _reindex(self):
        from controls import title_initial
        self._indices={}
        self._initials=[]
        self._first_by_letter={}
        for index,game in enumerate(self.visible):
            self._indices.setdefault(game['id'],index)
            initial=title_initial(game['title'])
            self._initials.append(initial)
            self._first_by_letter.setdefault(initial,index)
        self._letters=sorted(self._first_by_letter)
        self._letter_indices={letter:index for index,letter in enumerate(self._letters)}

    @property
    def letters(self): return list(self._letters)

    @property
    def letter_index(self):
        index=self.index
        return self._letter_indices.get(self._initials[index],0) if index>=0 else 0

    def letter_target(self, step):
        if not self._letters: return None
        if len(self._letters)==1: return self.index
        target=(self.letter_index+(1 if step>0 else -1))%len(self._letters)
        return self._first_by_letter[self._letters[target]]

    def filter(self, query=None, category=None):
        if query is not None:
            self.query = query
        if category is not None:
            self.category = category
        needle = normalized(self.query.strip())
        self.visible = [game for game in self.games
                        if (not self.category or self.category in game.get('categories', []))
                        and needle in normalized(game['title'] + ' ' + str((game.get('metadata') or {}).get('title') or ''))]
        self._reindex()
        if self.index < 0:
            self.selected_id = self.visible[0]['id'] if self.visible else None

    def select(self, index):
        if self.visible:
            self.selected_id = self.visible[index % len(self.visible)]['id']

    def move(self, delta):
        self.select(max(0, self.index) + delta)
