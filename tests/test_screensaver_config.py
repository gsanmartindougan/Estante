from unittest import TestCase
from screensaver_config import time_choice, time_seconds


class ScreensaverConfigTests(TestCase):
    def test_time_selector_has_1_to_60_values_and_seconds_or_minutes(self):
        for kind in ('idle', 'slide'):
            for unit, multiplier in (('seconds', 1), ('minutes', 60)):
                for value in (1, 30, 60):
                    settings = {'screensaver_' + kind + '_value': value,
                                'screensaver_' + kind + '_unit': unit}
                    self.assertEqual(time_choice(settings, kind), (value, unit))
                    self.assertEqual(time_seconds(settings, kind), value * multiplier)
            self.assertEqual(time_choice({'screensaver_' + kind + '_value': 90}, kind)[0], 60)
            self.assertEqual(time_choice({'screensaver_' + kind + '_value': 0}, kind)[0], 1)

    def test_existing_saved_times_keep_their_original_duration(self):
        self.assertEqual(time_seconds({'screensaver_minutes': 5}, 'idle'), 300)
        self.assertEqual(time_seconds({'screensaver_interval': 90}, 'slide'), 90)
        self.assertEqual(time_choice({'screensaver_interval': 120}, 'slide'), (2, 'minutes'))
        settings = {'screensaver_minutes': 5, 'screensaver_idle_value': 10, 'screensaver_idle_unit': 'seconds'}
        self.assertEqual(time_seconds(settings, 'idle'), 10)
