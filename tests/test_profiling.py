from unittest import TestCase
from unittest.mock import patch
import profiling


class ProfilingTests(TestCase):
    def tearDown(self):
        profiling.reset()

    def test_disabled_instrumentation_returns_original_function(self):
        def original():
            return 3
        with patch.object(profiling, 'ENABLED', False):
            self.assertIs(profiling.timed('disabled')(original), original)
        self.assertEqual(profiling.report(), {})

    def test_enabled_timings_preserve_returns_and_exceptions(self):
        with patch.object(profiling, 'ENABLED', True):
            @profiling.timed('work')
            def work(fail=False):
                if fail:
                    raise ValueError('failure')
                return 42
        with patch.object(profiling, 'perf_counter', side_effect=[1, 1.002, 2, 2.004]):
            self.assertEqual(work(), 42)
            with self.assertRaises(ValueError):
                work(True)
        row = profiling.report()['work']
        self.assertEqual(row['calls'], 2)
        self.assertEqual(row['total_ms'], 6)
        self.assertEqual(row['max_ms'], 4)
        self.assertEqual(row['p95_ms'], 4)
        profiling.reset()
        self.assertEqual(profiling.report(), {})

    def test_samples_remain_bounded(self):
        with patch.object(profiling, 'ENABLED', True):
            work = profiling.timed('bounded')(lambda: None)
        for _ in range(10005):
            work()
        result = profiling.report()['bounded']
        self.assertEqual(result['calls'], 10005)
        self.assertEqual(result['sample_count'], 10000)

    def test_counters_are_disabled_normally_and_reset_with_timings(self):
        with patch.object(profiling, 'ENABLED', False):
            profiling.count('disabled')
        self.assertEqual(profiling.counters(), {})
        with patch.object(profiling, 'ENABLED', True):
            profiling.count('hit')
            profiling.count('hit', 2)
        self.assertEqual(profiling.counters(), {'hit': 3})
        profiling.reset()
        self.assertEqual(profiling.counters(), {})
