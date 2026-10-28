from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from estante import Shelf
from image_cache import ImageCache, GdkPixbuf, reclaim_unused_memory
from library import Library
from screensaver import Screensaver, Slideshow, SaverPicture, background_paths, slideshow_paths, saver_size, saver_bounds


class ScreensaverTests(TestCase):
    def test_native_memory_reclamation_collects_cycles_and_tolerates_other_allocators(self):
        native = Mock()
        with patch('gc.collect', return_value=3), patch('ctypes.CDLL', return_value=native):
            report = reclaim_unused_memory()
        native.malloc_trim.assert_called_once_with(0)
        self.assertTrue(report['native_trim'])
        self.assertEqual(report['collected'], 3)
        with patch('gc.collect'), patch('ctypes.CDLL', side_effect=OSError('Unavailable')):
            self.assertFalse(reclaim_unused_memory()['native_trim'])

    def test_hidden_game_unloads_library_without_starting_slideshow(self):
        saver = Screensaver.__new__(Screensaver)
        shelf = Mock(selected_game='selected', settings={}, library_games=[], presentation_games=[{'id': 'old'}],
                     focus_revision=0, information_revision=0, reload_revision=0,
                     focus_timer=None, information_timer=None, scroll_animation=None,
                     background_tickets=[])
        for container in (shelf.grid_flow, shelf.horizontal_flow, shelf.carousel_flow,
                          shelf.list_flow, shelf.game_information):
            container.get_first_child.return_value = None
        saver.shelf = shelf
        saver.active = False
        saver.playing_sessions = set()
        saver.slides = Mock()
        saver.slide_host = SimpleNamespace(settings={})
        saver.release_images = Mock()
        with patch('screensaver.images') as cache:
            saver.suspend_for_game('game')
            self.assertTrue(shelf.library_suspended)
            self.assertEqual(shelf.library_games, [])
            self.assertEqual(shelf.presentation_games, [])
            shelf.library.release_state.assert_called_once()
            shelf.carousel_flow.stop_animation.assert_called_once()
            shelf.list_flow.stop_animation.assert_called_once()
            self.assertIsNone(saver.focus)
            cache.suspend.assert_called_once()
            saver.slides.start.assert_not_called()
            saver.slides.view.set_visible.assert_called_with(False)
            saver.game_finished('game')
            cache.resume.assert_called_once()
            self.assertFalse(shelf.library_suspended)
            self.assertEqual(shelf.selected_game, 'selected')
            shelf.reload.assert_called_once()

    def test_backgrounds_are_unique_existing_paths_without_game_metadata(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'image'
            path.touch()
            self.assertEqual(background_paths([
                {'banner': str(path), 'banner_secondary': str(path), 'metadata': {'large': 'data'}},
                {'banner': str(path / 'missing')}, {}]), [str(path.resolve())])

    def test_unloaded_library_restores_saved_state_without_rescanning(self):
        with TemporaryDirectory() as folder:
            library = Library(home=folder, data_dir=folder)
            library.state['games'] = [{'id': 'test', 'title': 'Remember me'}]
            library.save()
            library.release_state()
            self.assertIsNone(library._state)
            with patch.object(library, 'discover_faugus', side_effect=AssertionError('No scan')):
                self.assertEqual(library.state['games'][0]['id'], 'test')

    def test_idle_waits_blocks_during_game_and_also_activates_from_settings(self):
        saver = Screensaver.__new__(Screensaver)
        saver.active = False
        saver.last_activity = 0
        saver.start = Mock()
        saver.preview = saver.start
        shelf = Mock(settings={'screensaver_enabled': True, 'screensaver_minutes': 1},
                     running_sessions=set(), scrape_running=False, square_active=0)
        shelf.drawer.get_reveal_child.return_value = False
        shelf.pages.get_visible_child_name.return_value = 'library'
        saver.shelf = shelf
        with patch('screensaver.time.monotonic', return_value=59):
            saver.check()
        saver.start.assert_not_called()
        with patch('screensaver.time.monotonic', return_value=61):
            saver.check()
        saver.start.assert_called_once()
        saver.start.reset_mock()
        shelf.running_sessions = {'game'}
        with patch('screensaver.time.monotonic', return_value=100):
            saver.check()
        self.assertEqual(saver.last_activity, 100)
        shelf.running_sessions.clear()
        shelf.pages.get_visible_child_name.return_value = 'settings'
        with patch('screensaver.time.monotonic', return_value=200):
            saver.check()
        saver.start.assert_called_once()

    def test_wake_button_is_consumed_before_navigation(self):
        saver = Mock()
        saver.activity.return_value = True
        shelf = SimpleNamespace(screensaver=saver)
        self.assertTrue(Shelf.navigate(shelf, 'confirm', True))
        self.assertTrue(Shelf.key_pressed(shelf, None, 0, 0, 0))
        self.assertEqual(saver.activity.call_count, 2)

    def test_suspend_cancels_queued_jobs_and_releases_textures(self):
        cache = ImageCache()
        cache.entries['image'] = (object(), 16)
        cache.bytes = 16
        with cache.lock:
            ticket = cache.request('/queued', 10, 10, Mock())
            cache.suspend()
        self.assertTrue(ticket.cancelled)
        self.assertEqual(cache.bytes, 0)
        self.assertFalse(cache.entries)
        self.assertFalse(cache.pending)
        self.assertTrue(cache.request('/while-asleep', 10, 10, Mock()).cancelled)
        cache.resume()
        self.assertFalse(cache.suspended)

    def test_inflight_decode_cannot_repopulate_cache_after_suspend_and_resume(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'image.png'
            pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 8, 8)
            pixbuf.fill(0x123456ff)
            path.write_text('test')
            cache = ImageCache()
            started, proceed = Event(), Event()
            def decode(*_):
                started.set()
                proceed.wait(2)
                return pixbuf
            with patch('image_cache.decode_pixbuf', side_effect=decode), patch('image_cache.GdkPixbuf.Pixbuf.get_file_info', return_value=(object(), 8, 8)):
                worker = Thread(target=cache.load, args=(path, 8, 8))
                worker.start()
                try:
                    self.assertTrue(started.wait(2))
                    cache.suspend()
                    cache.resume()
                finally:
                    proceed.set()
                    worker.join(2)
            self.assertFalse(cache.entries)
            self.assertEqual(cache.bytes, 0)

    def test_same_window_overlay_restores_settings_without_discarding_drafts(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'background'
            path.touch()
            saver = Screensaver.__new__(Screensaver)
            shelf = Mock(selected_game='game-42', settings={}, active_category='Souls',
                         library_games=[{'banner': str(path)}],
                         focus_revision=1, information_revision=1, reload_revision=1,
                         focus_timer=None, information_timer=None, scroll_animation=None,
                         background_tickets=[])
            shelf.pages.get_visible_child_name.return_value = 'settings'
            shelf.pages.get_visible.return_value = True
            for container in (shelf.grid_flow, shelf.horizontal_flow, shelf.carousel_flow, shelf.list_flow,
                              shelf.game_information):
                container.get_first_child.return_value = None
            draft_view = shelf.preferences_view
            focus = shelf.get_focus()
            shelf.library_scroll.get_hadjustment().get_value.return_value = 12
            shelf.library_scroll.get_vadjustment().get_value.return_value = 400
            saver.shelf = shelf
            saver.slides = Mock()
            saver.slide_host = SimpleNamespace(settings={})
            saver.release_images = Mock()
            callbacks = []
            with patch('screensaver.images') as images, patch('screensaver.GLib.timeout_add',
                    side_effect=lambda delay, callback: callbacks.append(callback)):
                self.assertTrue(saver.start({'screensaver_dim': 50}))
                self.assertTrue(saver.active)
                self.assertTrue(shelf.library_suspended)
                self.assertIs(shelf.preferences_view, draft_view)
                self.assertEqual(saver.slide_host.settings['screensaver_dim'], 50)
                shelf.library.release_state.assert_called_once()
                self.assertTrue(saver.activity(), 'Wake input must be consumed')
                self.assertFalse(saver.active)
                self.assertFalse(shelf.library_suspended)
                self.assertEqual(shelf.selected_game, 'game-42')
                self.assertEqual(shelf.active_category, 'Souls')
                callbacks[-1]()
                focus.grab_focus.assert_called_once()
                shelf.library_scroll.get_hadjustment().set_value.assert_called_once_with(12)
                shelf.library_scroll.get_vadjustment().set_value.assert_called_once_with(400)
                images.suspend.assert_called_once()
                images.resume.assert_called_once()
            saver.slides.view.set_visible.assert_any_call(True)
            saver.slides.view.set_visible.assert_any_call(False)
            shelf.pages.set_visible.assert_any_call(False)
            shelf.pages.set_visible.assert_any_call(True)
            shelf.pages.set_visible_child_name.assert_not_called()
            shelf.leave_preferences.assert_not_called()
            shelf.discard_preferences.assert_not_called()
            shelf.destroy.assert_not_called()
            shelf.close.assert_not_called()
            self.assertIs(shelf.preferences_view, draft_view)

    def test_slideshow_releases_previous_image_after_transition(self):
        saver = Slideshow.__new__(Slideshow)
        saver.active = True
        saver.revision = 1
        saver.ticket = None
        saver.index = -1
        saver.slot = 1
        saver.retire_timer = None
        saver.paths = ['/one', '/two', '/three']
        saver.shelf = Mock(settings={'screensaver_dim': 40})
        saver.shelf.get_width.return_value = 2560
        saver.shelf.get_height.return_value = 1440
        saver.shelf.get_scale_factor.return_value = 2
        saver.pictures = [Mock(), Mock()]
        saver.view = Mock()
        saver.cache = Mock()
        callbacks = []
        with patch('screensaver.GLib.timeout_add', side_effect=lambda delay, fn: callbacks.append(fn) or 1):
            for i in range(3):
                saver.advance()
                args = saver.cache.request.call_args.args
                self.assertEqual(args[1:3], (1920, 1080))
                args[3](('texture-' + str(i), 'ambient-' + str(i), 2560), None)
                current, previous = saver.pictures[saver.slot], saver.pictures[1 - saver.slot]
                self.assertEqual(current.dim, .4)
                self.assertEqual(current.ambient, 'ambient-' + str(i))
                callbacks[-1]()
                previous.set_paintable.assert_called_with(None)
                self.assertIsNone(previous.ambient)
        self.assertEqual(saver.slot, 0)
        saver.cache.retain_paths.assert_not_called()

    def test_small_panoramic_image_is_centered_without_crop_or_stretch(self):
        x, y, width, height = saver_bounds(2560, 1440, 920, 430)
        self.assertEqual(width / height, 920 / 430)
        self.assertLessEqual(width / 920, 1.5)
        self.assertEqual(x + width / 2, 1280)
        self.assertEqual(y + height / 2, 720)
        self.assertGreater(x, 0)
        self.assertGreater(y, 0)

    def test_decode_budget_preserves_actual_display_shape(self):
        for width, height in ((5120, 2880), (2560, 1440), (1920, 1080),
                              (5120, 1440), (3440, 1440), (2160, 3840), (800, 600)):
            w, h = saver_size(width, height)
            self.assertLessEqual(w * h, 2_073_600)
            self.assertLessEqual(w, width)
            self.assertLessEqual(h, height)
            self.assertAlmostEqual(w / h, width / height, delta=.01)
        self.assertEqual(saver_size(800, 600), (800, 600))
        self.assertGreater(saver_size(5120, 1440)[0], 1920)

    def test_large_original_still_fills_4k_when_decode_is_reduced(self):
        bounds = saver_bounds(3840, 2160, 1920, 1080, source_width=3840)
        self.assertEqual(bounds, (0, 0, 3840, 2160))

    def test_snapshot_dims_foreground_and_ambient_without_gpu_blur(self):
        snapshot = Mock()
        texture = Mock()
        texture.get_width.return_value = 920
        texture.get_height.return_value = 430
        picture = Mock(ambient=object(), dim=.35, source_width=920)
        picture.get_width.return_value = 2560
        picture.get_height.return_value = 1440
        picture.get_paintable.return_value = texture
        SaverPicture.do_snapshot(picture, snapshot)
        self.assertEqual(snapshot.append_texture.call_count, 2)
        self.assertAlmostEqual(snapshot.append_color.call_args.args[0].alpha, .35, places=5)
        snapshot.push_blur.assert_not_called()


    def test_first_mouse_motion_wakes_even_without_previous_pointer_position(self):
        shelf = SimpleNamespace(screensaver=Mock(active=True), pointer_position=None, show_pointer=Mock())
        Shelf.pointer_moved(shelf, None, 10, 20)
        shelf.screensaver.activity.assert_called_once()
        shelf.show_pointer.assert_called_once()

    def test_visible_unfocused_window_still_enters_screensaver(self):
        saver = Screensaver.__new__(Screensaver)
        saver.active = False
        saver.last_activity = 0
        saver.start = Mock()
        saver.preview = saver.start
        saver.shelf = Mock(settings={'screensaver_enabled': True, 'screensaver_minutes': 1},
                           running_sessions=set(), scrape_running=False, square_active=0)
        saver.shelf.is_active.return_value = False
        saver.shelf.get_visible.return_value = True
        saver.shelf.drawer.get_reveal_child.return_value = False
        saver.shelf.pages.get_visible_child_name.return_value = 'library'
        with patch('screensaver.time.monotonic', return_value=61):
            saver.check()
        saver.start.assert_called_once()

    def test_preview_restores_page_if_suspension_fails(self):
        saver = Screensaver.__new__(Screensaver)
        saver.active = True
        saver.shelf = Mock(running_sessions=set())
        saver.start = Mock(side_effect=RuntimeError('test failure'))
        saver.stop = Mock()
        self.assertFalse(saver.preview())
        saver.stop.assert_called_once()
        self.assertIn('test failure', saver.shelf.error.call_args.args[0])

    def test_preview_reports_missing_backgrounds(self):
        saver = Screensaver.__new__(Screensaver)
        saver.active = False
        saver.shelf = Mock(running_sessions=set())
        saver.start = Mock(return_value=False)
        self.assertFalse(saver.preview())
        saver.shelf.error.assert_called_once()

    def test_stationary_mouse_event_does_not_wake_screensaver(self):
        shelf = SimpleNamespace(screensaver=Mock(active=True), pointer_position=(10, 20), show_pointer=Mock())
        Shelf.pointer_moved(shelf, None, 10, 20)
        shelf.screensaver.activity.assert_not_called()
        shelf.show_pointer.assert_not_called()

    def test_controller_can_wake_unfocused_screensaver_but_not_navigate_background_library(self):
        shelf = SimpleNamespace(is_active=lambda: False, screensaver=SimpleNamespace(active=True))
        self.assertTrue(Shelf.controls_active(shelf))
        shelf.screensaver.active = False
        self.assertFalse(Shelf.controls_active(shelf))

    def test_stale_slide_callback_cannot_clear_new_request_after_wake(self):
        saver = Slideshow.__new__(Slideshow)
        saver.active = True
        saver.revision = 1
        saver.ticket = None
        saver.index = -1
        saver.paths = ['/one']
        saver.shelf = Mock()
        saver.shelf.get_width.return_value = 1920
        saver.shelf.get_height.return_value = 1080
        saver.shelf.get_scale_factor.return_value = 1
        saver.cache = Mock()
        saver.advance()
        loaded = saver.cache.request.call_args.args[3]
        saver.revision = 2
        new_ticket = object()
        saver.ticket = new_ticket
        loaded(('texture', 'ambient', 1920), None)
        self.assertIs(saver.ticket, new_ticket)

    def test_preview_never_replaces_process_during_metadata_or_artwork_work(self):
        for job in ('scrape_running', 'square_active'):
            saver = Screensaver.__new__(Screensaver)
            saver.shelf = SimpleNamespace(running_sessions=set(), error=Mock(), **{job: True})
            saver.start = Mock()
            self.assertFalse(saver.preview())
            saver.start.assert_not_called()
            saver.shelf.error.assert_called_once()

    def test_application_background_works_without_any_library_games(self):
        from backgrounds import BUNDLED_BACKGROUNDS
        self.assertTrue(BUNDLED_BACKGROUNDS)
        path = BUNDLED_BACKGROUNDS[-1]
        self.assertEqual(slideshow_paths([], {'screensaver_source': 'application',
                                             'screensaver_background': 'bundled:' + path.name}), [str(path)])

    def test_game_source_never_uses_application_background(self):
        self.assertEqual(slideshow_paths([], {'screensaver_source': 'games',
                                             'screensaver_background': 'bundled:6.png'}), [])

    def test_one_second_interval_finishes_transition_before_next_slide(self):
        slides = Slideshow.__new__(Slideshow)
        slides.shelf = Mock(settings={'screensaver_slide_value': 1, 'screensaver_slide_unit': 'seconds'})
        slides.cache = Mock()
        slides.view = Mock()
        slides.advance = Mock()
        slides.revision = 0
        with patch('screensaver.GLib.timeout_add_seconds') as timer:
            slides.start(['/one', '/two'])
        timer.assert_called_once_with(1, slides.advance)
        self.assertLess(slides.transition_ms + 100, 1000)

    def test_single_application_background_does_not_redecode_on_a_timer(self):
        slides = Slideshow.__new__(Slideshow)
        slides.shelf = Mock(settings={})
        slides.cache = Mock()
        slides.view = Mock()
        slides.advance = Mock()
        slides.revision = 0
        with patch('screensaver.GLib.timeout_add_seconds') as timer:
            slides.start(['/one'])
        timer.assert_not_called()
        slides.advance.assert_called_once()

    def test_playing_screensaver_ignores_input_until_last_game_closes(self):
        saver = Screensaver.__new__(Screensaver)
        saver.playing_sessions = set()
        saver.active = False
        saver.shelf = Mock(settings={}, library_games=[])
        def start(settings):
            saver.active = True
            return True
        saver.start = Mock(side_effect=start)
        saver.stop = Mock()
        saver.game_started('one')
        saver.game_started('two')
        saver.start.assert_called_once()
        self.assertTrue(saver.activity())
        saver.stop.assert_not_called()
        saver.game_finished('one')
        saver.stop.assert_not_called()
        saver.game_finished('two')
        saver.stop.assert_called_once()
        self.assertEqual(saver.playing_sessions, set())
        self.assertEqual(saver.start.call_args.args[0]['screensaver_source'], 'application')


class SaverExitCleanupTests(TestCase):
    def test_exit_reclaims_after_restoration_and_skips_if_saver_restarts(self):
        for restarted in (False, True):
            saver = Screensaver.__new__(Screensaver)
            shelf = Mock(reload_revision=4)
            saver.shelf = shelf
            saver.slides = Mock()
            saver.pages_visible = True
            saver.selection = 'selected'
            saver.focus = None
            saver.scroll = (0, 0)
            with patch('screensaver.images'), patch('screensaver.GLib.timeout_add') as timer, \
                 patch('screensaver.reclaim_unused_memory') as reclaim:
                saver.stop()
                cleanup = next(call.args[1] for call in timer.call_args_list if call.args[0] == 750)
                reclaim.assert_not_called()
                saver.active = restarted
                self.assertFalse(cleanup())
                self.assertEqual(reclaim.call_count, int(not restarted))
