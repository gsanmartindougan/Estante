import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from heroic_import import discover_heroic, launch_url
from library import Library, launch_command, launch
from game_session import game_processes, wait_for_game


class HeroicTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.config=self.home/'config';self.heroic=self.config/'heroic'
        self.directory=self.home/'games/A game';self.directory.mkdir(parents=True)
        context=patch.dict(os.environ, XDG_CONFIG_HOME=str(self.config), XDG_DATA_HOME=str(self.home/'data'))
        context.start();self.addCleanup(context.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))

    def epic(self, root=None, name='abc'):
        root=root or self.heroic
        file=root/'legendaryConfig/legendary/installed.json'
        self.write(file,{name:dict(app_name=name,title='Epic Game',install_path=str(self.directory),executable='Game.exe')})
        self.write(file.parent/'metadata'/f'{name}.json', {'app_title':'Epic Game','metadata':{'keyImages':[{'type':'DieselGameBoxTall','url':'https://cdn.example/cover.png'}]}})
        return file

    def test_all_stores_and_sideload_local_artwork(self):
        self.epic()
        cover=self.heroic/'covers/local.png';cover.parent.mkdir();cover.touch()
        self.write(self.heroic/'gog_store/installed.json',{'installed':[dict(appName='123',install_path=str(self.directory),executable='gog.exe')]})
        self.write(self.heroic/'store_cache/gog_library.json',{'games':[dict(app_name='123',title='GOG Game',art_cover=str(cover))]})
        self.write(self.heroic/'nile_config/nile/installed.json',[dict(id='amazon-id',path=str(self.directory))])
        self.write(self.heroic/'nile_config/nile/library.json',[{'product':{'id':'amazon-id','title':'Amazon Game'}}])
        (self.directory/'local.exe').touch()
        self.write(self.heroic/'sideload_apps/library.json',{'games':[dict(app_name='local-id',title='Local Game',is_installed=True,install={'executable':str(self.directory/'local.exe')})]})
        games=discover_heroic(self.home,self.config)
        self.assertEqual({g['heroic_runner'] for g in games},{'legendary','gog','nile','sideload'})
        self.assertEqual(next(g['cover'] for g in games if g['heroic_runner']=='gog'),str(cover))
        self.assertEqual(next(g['heroic_artwork']['cover'] for g in games if g['heroic_runner']=='legendary'),'https://cdn.example/cover.png')
        self.assertEqual(next(g['title'] for g in games if g['heroic_runner']=='nile'),'Amazon Game')

    def test_flatpak_and_native_are_deduplicated(self):
        self.epic()
        root=self.home/'.var/app/com.heroicgameslauncher.hgl/config/heroic'
        self.epic(root);self.epic(root,'other')
        games=discover_heroic(self.home,self.config)
        self.assertEqual(len(games),2)
        self.assertEqual(next(g['install'] for g in games if g['heroic_app_name']=='abc'),'native')
        self.assertEqual(next(g['install'] for g in games if g['heroic_app_name']=='other'),'flatpak')

    def test_legacy_legendary_missing_install_and_dlc(self):
        self.heroic.mkdir(parents=True)
        self.write(self.config/'legendary/installed.json',{
            'good':dict(title='Installed',install_path=str(self.directory)),
            'dlc':dict(title='DLC',install_path=str(self.directory),is_dlc=True),
            'missing':dict(title='Missing',install_path='/no-such-game-directory')})
        self.assertEqual([g['heroic_app_name'] for g in discover_heroic(self.home,self.config)],['good'])

    def test_manual_scan_overrides_exclusion_and_uninstall(self):
        source=self.epic();original=source.read_bytes()
        lib=Library(home=self.home)
        self.assertEqual(lib.games(),[])
        self.assertEqual(lib.scan_heroic(),(1,1))
        game=lib.games()[0]
        self.assertEqual(game['categories'],['Heroic'])
        lib.put(dict(game,cover='/custom.png',metadata={'title':'Edited'},categories=['Heroic','Favorites']))
        self.assertEqual(lib.scan_heroic(),(0,1))
        game=Library(home=self.home).games()[0]
        self.assertEqual(game['cover'],'/custom.png')
        self.assertEqual(game['metadata']['title'],'Edited')
        self.assertEqual(game['categories'],['Heroic','Favorites'])
        lib.remove(game);self.assertEqual(lib.scan_heroic(),(0,0));self.assertEqual(lib.games(),[])
        lib.restore_excluded_imports();lib.scan_heroic();self.assertEqual(lib.games()[0]['cover'],'/custom.png')
        self.assertEqual(source.read_bytes(),original)
        source.unlink();lib.scan_heroic();self.assertEqual(lib.games(),[])

    def test_safe_native_and_flatpak_launch_url(self):
        game=dict(kind='heroic',heroic_runner='gog',heroic_app_name='ID & name/á',install='native')
        with patch('library.shutil.which',return_value='/usr/bin/heroic'):
            command,cwd=launch_command(game)
        self.assertEqual(command[:2],['/usr/bin/heroic','--no-gui'])
        self.assertIn('appName=ID+%26+name%2F%C3%A1',command[-1]);self.assertIsNone(cwd)
        with patch('library.shutil.which',return_value='flatpak'):
            self.assertEqual(launch_command(dict(game,install='flatpak'))[0][:4],['flatpak','run','com.heroicgameslauncher.hgl','--no-gui'])
        with patch('library.shutil.which',return_value=None), self.assertRaises(ValueError):launch_command(game)
        with self.assertRaises(ValueError):launch_url(dict(game,heroic_runner='unknown'))

    def test_existing_heroic_session_tracks_game_env_not_launcher_token(self):
        proc=self.home/'proc';proc.mkdir()
        for pid,runner,name in [(1,'gog','123'),(2,'legendary','123'),(3,'gog','other')]:
            folder=proc/str(pid);folder.mkdir()
            (folder/'stat').write_text(f'{pid} (wine) S 0 999 999 0')
            (folder/'environ').write_bytes(f'HEROIC_APP_NAME={name}\0HEROIC_APP_RUNNER={runner}\0ESTANTE_GAME_SESSION=old\0'.encode())
        game=dict(kind='heroic',heroic_runner='gog',heroic_app_name='123')
        self.assertEqual(game_processes(game,100,proc,session_token='new'),[1])

    def test_waits_for_heroic_game_even_if_cli_exits(self):
        process=Mock(pid=100);process.poll.return_value=0
        started=Mock()
        with patch('game_session.game_processes',side_effect=[[],[200],[200],[]]),patch('game_session.time.sleep'):
            self.assertEqual(wait_for_game({'kind':'heroic'},process,on_started=started),0)
        started.assert_called_once()

    def test_flatpak_session_token_is_forwarded(self):
        game=dict(kind='heroic',heroic_runner='gog',heroic_app_name='123',install='flatpak')
        with patch('library.shutil.which',return_value='flatpak'),patch('library.subprocess.Popen') as popen:
            launch(game,self.home)
        self.assertTrue(popen.call_args.args[0][2].startswith('--env=ESTANTE_GAME_SESSION='))

    def test_corrupt_manifest_does_not_replace_previous_library(self):
        file=self.epic();lib=Library(home=self.home);lib.scan_heroic()
        before=lib.file.read_bytes()
        file.write_text('{invalid')
        with self.assertRaises(ValueError):lib.scan_heroic()
        self.assertEqual(lib.file.read_bytes(),before)
        self.assertEqual(len(Library(home=self.home).games()),1)

    def test_heroic_and_steam_entries_can_be_edited_in_one_batch(self):
        self.epic();lib=Library(home=self.home);lib.scan_heroic()
        game=lib.games()[0]
        lib.put_many([dict(game,banner='/manual-banner.png')])
        lib.set_category_games('Heroic',[])
        self.assertEqual(lib.games()[0]['banner'],'/manual-banner.png')
        self.assertNotIn('Heroic',lib.games()[0]['categories'])
