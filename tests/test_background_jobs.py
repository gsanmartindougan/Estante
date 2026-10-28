from threading import Event
from unittest import TestCase
from unittest.mock import Mock
import weakref

from background_jobs import BackgroundJobs


class BackgroundJobsTests(TestCase):
    def test_concurrency_and_queue_are_bounded_and_cancelled_work_never_runs(self):
        entered, release = Event(), Event()
        dispatched = []
        pool = BackgroundJobs(dispatched.append, workers=1, max_pending=2)
        def blocking():
            entered.set()
            release.wait(2)
        pool.submit(blocking, Mock(), Mock(), 'old')
        self.assertTrue(entered.wait(2))
        obsolete = Mock()
        pool.submit(obsolete, Mock(), Mock(), 'old')
        pool.submit(obsolete, Mock(), Mock(), 'old')
        with self.assertRaises(RuntimeError):
            pool.submit(Mock(), Mock(), Mock(), 'overflow')
        pool.cancel('old')
        delivered = Event()
        pool.submit(lambda: 'current', lambda value: delivered.set(), Mock(), 'new')
        release.set()
        with pool.condition:
            self.assertTrue(pool.condition.wait_for(lambda: bool(dispatched), timeout=2))
        for callback in dispatched:
            callback()
        self.assertTrue(delivered.is_set())
        obsolete.assert_not_called()
        self.assertFalse(pool.jobs)

    def test_cancelling_already_queued_delivery_releases_callbacks_and_result(self):
        ready = Event()
        callbacks = []
        def dispatch(callback):
            callbacks.append(callback)
            ready.set()
        pool = BackgroundJobs(dispatch, workers=1)
        class Resource:
            pass
        resource = Resource()
        reference = weakref.ref(resource)
        result = [resource]
        def work():
            return result.pop()
        done = Mock()
        pool.submit(work, done, Mock(), 1)
        del resource
        self.assertTrue(ready.wait(2))
        # The worker clears locals before returning to wait; synchronize via its lock.
        with pool.condition:
            pass
        pool.cancel(1)
        self.assertIsNone(reference())
        callbacks[0]()
        done.assert_not_called()

    def test_failure_is_delivered_and_worker_survives(self):
        ready = Event()
        callbacks = []
        def dispatch(callback):
            callbacks.append(callback)
            ready.set()
        pool = BackgroundJobs(dispatch, workers=1)
        failed = Mock()
        def work():
            raise ValueError('broken')
        pool.submit(work, Mock(), failed, 1)
        self.assertTrue(ready.wait(2))
        callbacks.pop()()
        failed.assert_called_once_with('broken')
        ready.clear()
        done = Mock()
        pool.submit(lambda: 'ok', done, failed, 2)
        self.assertTrue(ready.wait(2))
        callbacks.pop()()
        done.assert_called_once_with('ok')
