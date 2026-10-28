from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from qt_app.editing import draft_for, save_draft
from library import Library


class QtEditingTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(data_dir=self.root)
        self.game = dict(id='game', title='Game', kind='custom', cover='/cover',
                         categories=['Fav'], metadata={'description':'Before', 'entity_id':'Q123',
                                                      'release_date':'2020-01-02'})
        self.library.put(self.game)
        self.original = draft_for(self.game)

    def test_save_preserves_unrelated_metadata_artwork_and_session_activity(self):
        self.library.put(dict(self.game, banner='/new-banner', metadata={**self.game['metadata'], 'publishers':['External']}))
        self.library.record_session(self.game, 7, 'date', 0)
        values = dict(self.original, description='Edited', release_date='03/04/2021', categories='Fav, Steam, Fav')
        result = save_draft(self.root, 'game', self.original, values)[0]
        self.assertEqual(result['banner'], '/new-banner')
        self.assertEqual(result['categories'], ['Fav', 'Steam'])
        self.assertEqual(result['metadata']['publishers'], ['External'])
        self.assertEqual(result['metadata']['entity_id'], 'Q123')
        self.assertEqual(result['metadata']['release_date'], '2021-04-03')
        self.assertTrue(result['metadata']['manually_edited'])
        self.assertEqual(Library(data_dir=self.root).game_stats(self.game)['sessions'], 1)

    def test_concurrent_same_field_change_is_reported_without_writing(self):
        self.library.put(dict(self.game, metadata={**self.game['metadata'], 'description':'External'}))
        before = self.library.file.read_bytes()
        with self.assertRaisesRegex(ValueError, 'description'):
            save_draft(self.root, 'game', self.original, dict(self.original, description='Edited'))
        self.assertEqual(self.library.file.read_bytes(), before)

    def test_invalid_date_and_reserved_category_leave_file_unchanged(self):
        before = self.library.file.read_bytes()
        for values in (dict(self.original, release_date='31/02/2020'), dict(self.original, categories='Todos')):
            with self.assertRaises(ValueError):
                save_draft(self.root, 'game', self.original, values)
        self.assertEqual(self.library.file.read_bytes(), before)

    def test_deleted_game_is_not_resurrected(self):
        self.library.remove(self.game)
        with self.assertRaisesRegex(ValueError, 'ya no'):
            save_draft(self.root, 'game', self.original, dict(self.original, description='Edited'))
        self.assertEqual(Library(data_dir=self.root).games(), [])

    def test_imported_override_uses_existing_format(self):
        imported = dict(self.game, kind='steam', id='steam:1')
        self.library.state['steam'] = [imported]; self.library.save()
        save_draft(self.root, imported['id'], draft_for(imported), dict(draft_for(imported), genres='RPG, Action'))
        reopened = Library(data_dir=self.root)
        self.assertEqual(reopened.state['overrides']['steam:1']['metadata']['genres'], ['RPG', 'Action'])
        self.assertEqual(reopened.state['steam'][0], imported)

    def test_existing_invalid_date_can_be_corrected(self):
        game = dict(self.game, metadata={'release_date':'bad date'})
        self.library.put(game)
        original = draft_for(game)
        saved = save_draft(self.root, 'game', original, dict(original, release_date='2024-01-02'))[0]
        self.assertEqual(saved['metadata']['release_date'], '2024-01-02')
