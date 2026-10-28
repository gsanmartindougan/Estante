from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from library import Library
from qt_app.session import run_session


class QtSessionTests(TestCase):
    def test_finished_game_is_recorded_once_against_latest_library(self):
        with TemporaryDirectory() as root:
            game = dict(id='test', title='Test', kind='local', path='/bin/true')
            library = Library(data_dir=root)
            library.put(game)
            events = []
            def wait(game, process, on_started, **options):
                on_started()
                latest = Library(data_dir=root)
                latest.put(dict(game, title='Edited while running'))
                return 0
            with patch('qt_app.session.launch', return_value=Mock()), \
                 patch('qt_app.session.wait_for_game', side_effect=wait):
                run_session(game, root, {}, ['qt'], False, events.append)
            reopened = Library(data_dir=root)
            self.assertEqual(reopened.games()[0]['title'], 'Edited while running')
            self.assertEqual(reopened.game_stats(game)['sessions'], 1)
            self.assertEqual([e[0] for e in events], ['started', 'finished'])

    def test_supervisor_handoff_uses_qt_reopen_and_never_double_records(self):
        with TemporaryDirectory() as root:
            game = dict(id='test', title='Test')
            folder = Path(root)/'supervisor'; folder.mkdir()
            events = []
            def emit(event):
                events.append(event)
                if event[0] == 'handoff':
                    path, acknowledged = event[1]
                    (path/'handoff').touch()
                    acknowledged.set()
            def wait(game, process, on_started, **options):
                self.assertTrue(callable(options.get('is_ready')))
                on_started()
                self.fail('Monitoring must transfer to supervisor')
            with patch('qt_app.session.launch', return_value=Mock()), \
                 patch('qt_app.session.wait_for_game', side_effect=wait), \
                 patch('qt_app.session.game_supervisor.prepare', return_value=folder) as prepare, \
                 patch('qt_app.session.Library') as library:
                run_session(game, root, {'selected_game':'test'}, ['python', 'qt_app/main.py'], True, emit)
            self.assertEqual(prepare.call_args.kwargs['reopen'], ['python', 'qt_app/main.py'])
            library.assert_not_called()
            self.assertEqual([e[0] for e in events], ['started', 'handoff'])

    def test_supervisor_failure_keeps_local_monitoring(self):
        with TemporaryDirectory() as root:
            game = dict(id='test', title='Test', kind='local')
            events = []
            def wait(game, process, on_started, **options):
                on_started()
                return 0
            with patch('qt_app.session.launch', return_value=Mock()), \
                 patch('qt_app.session.wait_for_game', side_effect=wait), \
                 patch('qt_app.session.game_supervisor.prepare', side_effect=RuntimeError('no systemd')):
                run_session(game, root, {}, ['qt'], True, events.append)
            self.assertEqual([e[0] for e in events], ['started', 'warning', 'finished'])
            self.assertEqual(Library(data_dir=root).game_stats(game)['sessions'], 1)

    def test_launch_failure_is_reported_without_recording(self):
        events = []
        with TemporaryDirectory() as root, patch('qt_app.session.launch', side_effect=OSError('missing executable')), \
             patch('qt_app.session.Library') as library:
            run_session({}, root, {}, ['qt'], False, events.append)
        self.assertEqual(events, [('error', 'missing executable')])
        library.assert_not_called()

    def test_starting_screen_lasts_25_seconds_for_all_behaviors(self):
        for hide in (False, True):
            with self.subTest(hide=hide), TemporaryDirectory() as root:
                events=[]
                game={'id':'test','title':'Test','kind':'local'}
                def wait(game, process, on_started, is_ready):
                    self.assertFalse(is_ready([200]))  # At launch.
                    self.assertFalse(is_ready([200]))  # 24.9 seconds.
                    self.assertTrue(is_ready([200]))   # 25 seconds.
                    on_started()
                    return 0
                with patch('qt_app.session.launch',return_value=Mock()), patch('qt_app.session.wait_for_game',side_effect=wait), patch('qt_app.session.time.monotonic',side_effect=[100,100,124.9,125,126]), patch('qt_app.session.game_supervisor.prepare',side_effect=RuntimeError('test: keep local monitoring')):
                    run_session(game,root,{},['qt'],hide,events.append)
                self.assertEqual(events[0],('started',None))
                self.assertEqual(events[-1],('finished',0))

    def test_game_exiting_during_delay_never_hands_off(self):
        with TemporaryDirectory() as root:
            events=[]
            process=Mock(pid=100);process.poll.return_value=0
            game={'id':'test','title':'Test','kind':'steam','steam_appid':'10'}
            with patch('qt_app.session.launch',return_value=process), patch('game_session.game_processes',side_effect=[[200],[]]), patch('game_session.time.sleep'), patch('qt_app.session.time.monotonic',return_value=100), patch('qt_app.session.game_supervisor.prepare') as prepare:
                run_session(game,root,{},['qt'],True,events.append)
            prepare.assert_not_called()
            self.assertEqual(events,[('finished',0)])
