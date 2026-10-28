from threading import Event, get_ident
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from image_cache import ImageCache
from estante import Shelf


class AsyncImageTests(TestCase):
    def test_worker_prioritizes_selection_cancels_stale_and_dispatches_to_ui(self):
        cache = ImageCache()
        started, proceed, completed = Event(), Event(), Event()
        order, deliveries, threads = [], [], []
        main_thread = get_ident()
        def load(path, width, height, **kwargs):
            threads.append(get_ident())
            order.append(path.rsplit('/', 1)[-1])
            if path.endswith('first'):
                started.set()
                proceed.wait(2)
            return path
        def dispatch(callback):
            deliveries.append(callback)
            if len(deliveries) == 3:
                completed.set()
        callback = Mock()
        try:
            with patch.object(cache, 'load', side_effect=load), patch('image_cache.GLib.idle_add', side_effect=dispatch):
                cache.request('/first', 10, 10, callback)
                self.assertTrue(started.wait(2))
                cache.request('/neighbour', 10, 10, callback, priority=1)
                cancelled = cache.request('/stale', 10, 10, callback)
                cancelled.cancelled = True
                cache.request('/selected', 10, 10, callback, priority=0)
                proceed.set()
                self.assertTrue(completed.wait(2))
                self.assertEqual(order, ['first', 'selected', 'neighbour'])
                self.assertTrue(all(thread != main_thread for thread in threads))
                callback.assert_not_called()
                for delivery in deliveries:
                    delivery()
                self.assertEqual(callback.call_count, 3)
        finally:
            proceed.set()

    def test_discarding_pending_path_never_decodes_it(self):
        cache = ImageCache()
        # Hold the queue lock until all mutations are complete.
        with patch.object(cache, 'load') as decode:
            with cache.condition:
                ticket = cache.request('/obsolete', 10, 10, Mock())
                cache.retain_paths(['/current'])
                self.assertFalse(cache.pending)
                ticket.cancelled = True
            decode.assert_not_called()

    def test_picture_request_does_not_decode_on_ui_and_uses_hidpi(self):
        picture = Mock()
        host = SimpleNamespace(get_scale_factor=lambda: 2, view_mode='list')
        with patch('estante.images.request') as request, patch('estante.images.load') as decode:
            Shelf.request_picture(host, picture, '/logo', 300, 100, priority=0)
            decode.assert_not_called()
            args = request.call_args.args
            self.assertEqual(args[:3], ('/logo', 600, 200))
            self.assertEqual(args[4], 0)
            args[3]('texture', None)
            picture.set_paintable.assert_called_once_with('texture')

    def test_list_logos_use_display_pixels_and_only_selected_logo_uses_focus_zoom(self):
        for density in (1, 2):
            for zoom in (100, 150, 250):
                for priority in (0, 1):
                    host = SimpleNamespace(get_scale_factor=lambda: density, view_mode='list',
                                           settings={'list_focus_zoom': zoom})
                    with patch('estante.images.request') as request:
                        Shelf.request_picture(host, Mock(), '/logo', 300, 100, priority, kind='logo')
                    factor = density * (zoom / 100 if priority == 0 else 1)
                    self.assertEqual(request.call_args.args[:3], ('/logo', 300 * factor, 100 * factor))
                    self.assertEqual(request.call_args.kwargs['kind'], 'logo')

    def test_grid_requests_display_pixels_without_focus_oversampling(self):
        for density in (1, 2):
            for width, height in ((156, 234), (312, 468), (156, 156)):
                with self.subTest(density=density, size=(width, height)):
                    picture = Mock()
                    host = SimpleNamespace(get_scale_factor=lambda: density, view_mode='grid')
                    with patch('estante.images.request') as request:
                        Shelf.request_picture(host, picture, '/cover', width, height)
                    self.assertEqual(request.call_args.args[:3],
                                     ('/cover', width * density, height * density))

    def test_list_selected_cover_is_loaded_at_display_resolution(self):
        for density in (1, 2):
            host = SimpleNamespace(get_scale_factor=lambda: density, view_mode='list')
            with patch('estante.images.request') as request:
                Shelf.request_picture(host, Mock(), '/cover', 180, 270, priority=0)
            self.assertEqual(request.call_args.args[:3], ('/cover', 180 * density, 270 * density))

    def test_other_layouts_load_neighbours_at_actual_hidpi_resolution(self):
        for mode in ('carousel', 'ps5'):
            with self.subTest(mode=mode), patch('estante.images.request') as request:
                host = SimpleNamespace(get_scale_factor=lambda: 2, view_mode=mode)
                Shelf.request_picture(host, Mock(), '/cover', 100, 150, priority=1)
                self.assertEqual(request.call_args.args[:3], ('/cover', 200, 300))

    def test_selected_covers_preserve_configured_focus_zoom(self):
        for mode, settings, expected in (
                ('carousel', {'carousel_zoom': 175}, (350, 525)),
                ('ps5', {'ps5_focus_size': 320}, (640, 960))):
            with self.subTest(mode=mode), patch('estante.images.request') as request:
                host = SimpleNamespace(get_scale_factor=lambda: 2, view_mode=mode, settings=settings)
                Shelf.request_picture(host, Mock(), '/cover', 104 if mode=='ps5' else 100,
                                      156 if mode=='ps5' else 150, priority=0)
                self.assertEqual(request.call_args.args[:3], ('/cover', *expected))

    def test_decode_errors_are_delivered_without_killing_worker(self):
        cache = ImageCache()
        finished = Event()
        callbacks = []
        def dispatch(callback):
            callbacks.append(callback)
            finished.set()
        done = Mock()
        with patch.object(cache, 'load', side_effect=ValueError('invalid image')), \
             patch('image_cache.GLib.idle_add', side_effect=dispatch):
            cache.request('/bad', 10, 10, done)
            self.assertTrue(finished.wait(2))
            callbacks[0]()
            self.assertIsNone(done.call_args.args[0])
            self.assertIsInstance(done.call_args.args[1], ValueError)

    def test_cancellation_after_decode_suppresses_ui_update(self):
        cache = ImageCache()
        finished = Event()
        callbacks = []
        def dispatch(callback):
            callbacks.append(callback)
            finished.set()
        done = Mock()
        with patch.object(cache, 'load', return_value='texture'), \
             patch('image_cache.GLib.idle_add', side_effect=dispatch):
            ticket = cache.request('/old', 10, 10, done)
            self.assertTrue(finished.wait(2))
            ticket.cancelled = True
            callbacks[0]()
            done.assert_not_called()

    def test_settings_previews_are_async_and_cancel_previous_request(self):
        cache = ImageCache()
        picture = Mock()
        previous = SimpleNamespace(cancelled=False)
        picture.image_ticket = previous
        ticket = SimpleNamespace(cancelled=False)
        with patch.object(cache, 'request', return_value=ticket) as request, patch.object(cache, 'load') as load:
            cache.request_picture(picture, '/preview', 480, 270)
            self.assertTrue(previous.cancelled)
            self.assertIs(picture.image_ticket, ticket)
            load.assert_not_called()
            request.call_args.args[3]('texture', None)
            picture.set_paintable.assert_called_once_with('texture')
            cache.request_picture(picture, '', 480, 270)
            self.assertTrue(ticket.cancelled)
            self.assertIsNone(picture.image_ticket)
            picture.set_paintable.assert_called_with(None)
