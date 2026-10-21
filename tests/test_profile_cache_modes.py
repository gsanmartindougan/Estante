from unittest import TestCase
from unittest.mock import Mock, patch
from tools.profile_rendering import main


class ProfileCacheModesTests(TestCase):
    def test_warm_comparison_prepares_each_variant_before_measuring(self):
        with patch('sys.argv', ['profile_rendering.py', '--compare', '--cache-state', 'warm']), \
             patch('tools.profile_rendering.subprocess.run', return_value=Mock(returncode=0)) as run:
            self.assertEqual(main(), 0)
        calls = [call.args[0] for call in run.call_args_list]
        self.assertEqual(len(calls), 4)
        self.assertIn('--prepare-cache', calls[0])
        self.assertNotIn('--prepare-cache', calls[1])
        self.assertIn('--prepare-cache', calls[2])
        self.assertNotIn('--prepare-cache', calls[3])
        self.assertNotIn('--no-blur', calls[0])
        self.assertIn('--no-blur', calls[2])
        for first, second in ((calls[0], calls[1]), (calls[2], calls[3])):
            self.assertEqual(first[first.index('--cache-dir')+1], second[second.index('--cache-dir')+1])
        self.assertNotEqual(calls[0][calls[0].index('--cache-dir')+1], calls[2][calls[2].index('--cache-dir')+1])
