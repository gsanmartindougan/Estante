from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import json
from library import Library
from qt_app.operations import save_local, update_game, save_settings
from qt_app.settings_schema import merge_values


class QtOperationsTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.script=self.root/'game.sh';self.script.write_text('#!/bin/sh\nexit 0\n')

    def test_local_edit_preserves_artwork_metadata_and_categories(self):
        identity=save_local(self.root,'First',str(self.script))
        update_game(self.root,identity,{'cover':'/cover','banner':'/banner','metadata':{'description':'text'},'categories':['Fav']})
        save_local(self.root,'Renamed',str(self.script),'--argument','',identity)
        game=Library(data_dir=self.root).games()[0]
        self.assertEqual((game['cover'],game['banner'],game['categories'],game['metadata']['description']),('/cover','/banner',['Fav'],'text'))
        self.assertEqual(game['title'],'Renamed')
        self.assertEqual(game['arguments'],'--argument')

    def test_invalid_local_does_not_write_and_imported_launch_is_protected(self):
        with self.assertRaises(ValueError):save_local(self.root,'','/missing')
        library=Library(data_dir=self.root)
        imported=dict(id='steam:1',kind='steam',title='Steam',steam_appid=1)
        library.state['steam']=[imported];library.save()
        original=library.file.read_bytes()
        with self.assertRaises(ValueError):save_local(self.root,'Changed',str(self.script),identity='steam:1')
        self.assertEqual(library.file.read_bytes(),original)

    def test_settings_atomic_merge_keeps_other_values_and_file_private(self):
        save_settings(self.root,{'unknown':{'retain':True},'steamgriddb_key':'secret'})
        settings=save_settings(self.root,{'layout':'carousel'})
        self.assertEqual(settings['unknown'],{'retain':True})
        self.assertEqual(settings['steamgriddb_key'],'secret')
        self.assertEqual((self.root/'settings.json').stat().st_mode&0o777,0o600)
        self.assertEqual(json.loads((self.root/'settings.json').read_text()),settings)

    def test_per_mode_settings_keep_other_modes_and_reject_invalid_values(self):
        original={'background_dim':{'grid':20,'list':30},'layout':'grid'}
        result=merge_values(original,[dict(path=['background_dim','list'],value=44),dict(path=['carousel_position'],value='bottom')])
        self.assertEqual(result['background_dim'],{'grid':20,'list':44})
        self.assertEqual(original['background_dim']['list'],30)
        for row in (dict(path=['background_dim','list'],value=101),dict(path=['background_dim','list'],value=float('nan')),dict(path=['playing_behavior'],value='invalid'),dict(path=['unknown'],value='x')):
            with self.assertRaises(ValueError):merge_values(original,[row])
