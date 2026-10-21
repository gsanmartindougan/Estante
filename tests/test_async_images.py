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
        host = SimpleNamespace(get_scale_factor=lambda: 2)
        with patch('estante.images.request') as request, patch('estante.images.load') as decode:
            Shelf.request_picture(host, picture, '/logo', 300, 100, priority=0)
            decode.assert_not_called()
            args = request.call_args.args
            self.assertEqual(args[:3], ('/logo', 1500, 500))
            self.assertEqual(args[4], 0)
            args[3]('texture', None)
            picture.set_paintable.assert_called_once_with('texture')

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
