from unittest import TestCase
from qt_app.catalog import Catalog


class QtCatalogTests(TestCase):
    def catalog(self):
        return Catalog([dict(id='a', title='Árbol', categories=['Favoritos']),
                        dict(id='b', title='Bloodborne', categories=['Steam']),
                        dict(id='c', title='Cyberpunk', categories=['Steam', 'Favoritos'])])

    def test_filter_combines_search_and_category_preserving_selection(self):
        catalog = self.catalog()
        catalog.select(2)
        catalog.filter(category='Steam')
        self.assertEqual((catalog.selected_id, catalog.index), ('c', 1))
        catalog.filter(query='blood')
        self.assertEqual(catalog.selected_id, 'b')
        catalog.filter(category='Favoritos')
        self.assertIsNone(catalog.selected)
        catalog.move(1)
        self.assertEqual(catalog.index, -1)

    def test_search_ignores_case_accents_and_whitespace(self):
        catalog = self.catalog()
        catalog.filter(query=' ARBOL ')
        self.assertEqual([game['id'] for game in catalog.visible], ['a'])
        self.assertEqual(len(catalog.games), 3)

    def test_wrapping_and_empty_library(self):
        catalog = self.catalog()
        catalog.move(-1)
        self.assertEqual(catalog.selected_id, 'c')
        catalog.move(1)
        self.assertEqual(catalog.selected_id, 'a')
        empty = Catalog([])
        empty.move(1)
        empty.filter(query='test', category='Steam')
        self.assertEqual(empty.index, -1)
        self.assertIsNone(empty.selected)
        self.assertEqual(empty.categories, [])

    def test_search_matches_manual_information_title_without_renaming_import(self):
        catalog = Catalog([dict(id='steam:1', title='Original', metadata={'title':'Título editado'})])
        catalog.filter(query='titulo')
        self.assertEqual(catalog.selected_id, 'steam:1')
        catalog.filter(query='original')
        self.assertEqual(catalog.selected_id, 'steam:1')

    def test_indexes_and_letters_refresh_after_reload_and_filter(self):
        from controls import alphabet_target
        catalog=self.catalog()
        for index in range(3):
            catalog.select(index)
            self.assertEqual(catalog.index,index)
            self.assertEqual(catalog.letters,['A','B','C'])
            for step in (-1,1):
                self.assertEqual(catalog.letter_target(step),alphabet_target([g['title'] for g in catalog.visible],index,step>0))
        catalog.games=[dict(id='z',title='Zelda'),dict(id='a',title='Árbol')]
        catalog.filter()
        self.assertEqual(catalog.selected_id,'z')
        self.assertEqual(catalog.letters,['A','Z'])
        catalog.filter(query='arbol')
        self.assertEqual((catalog.index,catalog.letter_index,catalog.letter_target(1)),(0,0,0))
        catalog.filter(query='missing')
        self.assertEqual(catalog.letters,[])
        self.assertIsNone(catalog.letter_target(1))
